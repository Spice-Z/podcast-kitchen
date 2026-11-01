"""Step 5-pre: per-track speech gating (config `gate`). Runs after level, before render.

Each speaker track is muted (gate.attenuation_db; "-inf" = full mute) outside its own speech regions:
  speech = own Silero VAD islands  ∪  aligned transcript segments (status != rejected)  ∪  laughs  ∪  backchannel candidates,
  where word spans count only where they overlap own VAD islands (pads anchored to VAD edges, smear dropped),
  minus non-speech transients: VAD islands <= transient_max_s without firm text (a word mostly inside the island),
  no laugh/backchannel, and low voicing (autocorr peak 80-400 Hz < voicing_max) or high spectral flatness (> flatness_min) — sniffs, coughs,
  throat-clears; plus unvoiced energy bursts inside padded regions but outside voiced VAD (pad zones, merged gaps),
  classified per sub-window. Regions are padded (pad_before_ms / pad_after_ms), gaps < merge_gap_ms merged, edges faded (fade_ms).
Room tone continuity: where every track is gated, the reference track (gate.fill_track) gets its own room tone
(render.roomtone: quietest VAD-free window that is also burst-free; source logged) faded in, so the mix never drops to digital silence.
Outputs work/gate/<spk>.wav (float), work/gate/regions.json, logs/gate.json (incl. the QA metric: transients in
non-speech regions before / after gating, per track). Gains are built on a 1 ms grid and interpolated per sample."""
import argparse
from pathlib import Path
import numpy as np
from common import dump, load, load_cfg, log_step, speakers, r

GRID = 1000  # gain grid, points per second


def merge(iv, gap):
    out = []
    for a, b in sorted(iv):
        if out and a - out[-1][1] < gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def voicing(y, sr):
    """Max normalized autocorrelation in the 80-400 Hz lag range (1 = strongly periodic)."""
    y = y - y.mean()
    if len(y) < sr // 40 or not np.any(y):
        return 0.0
    f = np.fft.rfft(y, 2 * len(y)); ac = np.fft.irfft(f * np.conj(f))[: len(y)]
    lo, hi = int(sr / 400), min(len(y) - 1, int(sr / 80))
    return float(ac[lo:hi].max() / (ac[0] + 1e-12)) if hi > lo else 0.0


def flatness(y):
    p = np.abs(np.fft.rfft(y * np.hanning(len(y)))) ** 2 + 1e-12
    return float(np.exp(np.mean(np.log(p))) / np.mean(p))


def classify(y, sr, g):
    v, fl = voicing(y, sr), flatness(y)
    return {"voicing": r(v, 3), "flatness": r(fl, 4), "transient": bool(v < g["voicing_max"] or fl > g["flatness_min"])}


def overl(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def frame_db(y, sr, hop=0.01):
    fr = max(1, int(hop * sr)); m = len(y) // fr
    if m == 0:
        return np.zeros(0)
    return 10 * np.log10(np.mean(y[: m * fr].reshape(m, fr) ** 2, axis=1) + 1e-12)


def track_floor(x, sr):
    """10th percentile of 10 ms frame levels (dB) = the track's noise floor (same reference as `bursts`)."""
    db = frame_db(x, sr)
    return float(np.percentile(db[db > -119], 10)) if np.any(db > -119) else -120.0


def firm_text(a, b, txt):
    """True when a transcript word is plausibly carried by VAD island [a, b): a word that mostly lies inside the island.
    A long smeared word that merely reaches the island does not count (alignment smear over a sniff)."""
    for x, y in txt:
        o = overl(a, b, x, y)
        if o > 0 and o >= 0.5 * (y - x):
            return True
    return False


def hot_runs(y, sr, thr, t0):
    """Runs (>= 30 ms) of 10 ms frames above thr dB, as absolute (start, end) seconds."""
    db = frame_db(y, sr); out, i = [], 0
    while i < len(db):
        if db[i] > thr:
            j = i
            while j < len(db) and db[j] > thr: j += 1
            if j - i >= 3: out.append((t0 + i / 100, t0 + j / 100))
            i = j
        else:
            i += 1
    return out


def subtract(iv, cuts):
    for c0, c1 in cuts:
        nxt = []
        for x, y in iv:
            if c1 <= x or c0 >= y: nxt.append([x, y]); continue
            if c0 > x: nxt.append([x, c0])
            if c1 < y: nxt.append([c1, y])
        iv = nxt
    return iv


def edge_tails(y, sr, g, thr, t0):
    """Unvoiced runs at the head/tail of a voiced VAD island (sniff or breath glued onto speech by VAD).
    Steps of 50 ms from each edge inward while voicing < voicing_max and level > thr; a run >= edge_tail_min_s is
    returned minus edge_keep_s next to the speech (protects unvoiced word-final consonants such as -su)."""
    st = int(0.05 * sr); n = len(y) // st
    vmin, keep = g.get("edge_tail_min_s", 0.2), g.get("edge_keep_s", 0.05)
    def unv(i):
        w = y[i * st:(i + 1) * st]
        return 10 * np.log10(np.mean(w ** 2) + 1e-12) > thr and voicing(w, sr) < g["voicing_max"]
    out = []
    i = n - 1
    while i >= 0 and unv(i): i -= 1
    tail = (n - 1 - i) * 0.05
    if tail >= vmin and i >= 0:
        out.append((t0 + (i + 1) * 0.05 + keep, t0 + len(y) / sr))
    j = 0
    while j < n and unv(j): j += 1
    if j * 0.05 >= vmin and j < n:
        out.append((t0, t0 + j * 0.05 - keep))
    return out


def speech_regions(s, vad, words, cands, laughs, read, sr, g, floor_db=None):
    """-> (padded merged regions, transients list). read(a, b) returns the track samples for [a, b) seconds.
    1. Word spans count only where they overlap own VAD islands (smear beyond VAD dropped); pads are anchored to VAD edges.
    2. Short VAD islands (<= transient_max_s) without firm text/laugh/backchannel are classified; unvoiced -> transient.
    3. Inside the padded regions, energy bursts outside voiced VAD islands (pad zones, merged gaps, smeared spans) are
       classified per sub-window; unvoiced bursts are muted. Unvoiced runs >= edge_tail_min_s at the head/tail of a
       voiced island (sniff glued onto speech) are muted too, keeping edge_keep_s next to the speech. Laughs and backchannels are never muted."""
    isl = [(a, b) for a, b in vad["speakers"][s]]
    txt = [(w["start"], w["end"]) for w in words.get(s, []) if w.get("status") != "rejected"]
    keep = [(c["start"], c["end"]) for c in cands if c["type"] == "backchannel" and c["track"] == s] + \
           [(a, b) for a, b, t in laughs if t == s]
    sp, trans, voiced = list(keep), [], []
    for a, b in isl:
        protected = any(overl(a, b, x, y) > 0 for x, y in keep)
        if b - a <= g["transient_max_s"] and not protected and not firm_text(a, b, txt):
            c = classify(read(a, b), sr, g)
            if c["transient"]:
                trans.append({"start": r(a), "end": r(b), "kind": "island", **c}); continue
        sp.append((a, b)); voiced.append((a, b))
    # words with no VAD support at all are dropped (alignment smear / ASR hallucination); their VAD parts are already in sp
    pb, pa = g["pad_before_ms"] / 1000, g["pad_after_ms"] / 1000
    padded = merge([(max(0.0, a - pb), b + pa) for a, b in sp], g["merge_gap_ms"] / 1000)
    # clip island transients back out where a neighbour's pad reaches them
    padded = subtract(padded, [(t["start"], t["end"]) for t in trans
                               if not any(overl(t["start"], t["end"], p, q) > 0 for p, q in sp)])
    # sub-window transient detection in the parts of each region not covered by voiced VAD or laughs/backchannels
    if floor_db is None:
        floor_db = g["noise_floor_min_db"]
    thr = max(floor_db, g["noise_floor_min_db"]) + g["transient_rise_db"]
    cuts = []
    for a, b in voiced:
        if b - a <= g["transient_max_s"] or any(overl(a, b, x, y) > 0 for x, y in keep): continue
        for c0, c1 in edge_tails(read(a, b), sr, g, thr, a):
            c = classify(read(c0, c1), sr, g)
            trans.append({"start": r(c0), "end": r(c1), "kind": "edge", **c}); cuts.append((c0, c1))
    firm = merge(subtract([list(v) for v in voiced], cuts) + [[max(0.0, a - pb), b + pa] for a, b in keep], 0.0)  # laughs/backchannels incl. their pads
    for a, b in padded:
        for x, y in subtract([[a, b]], firm):
            if y - x < 0.03: continue
            for h0, h1 in hot_runs(read(x, y), sr, thr, x):
                c0, c1 = max(x, h0 - 0.02), min(y, h1 + 0.02)
                c = classify(read(c0, c1), sr, g)
                if c["transient"]:
                    trans.append({"start": r(c0), "end": r(c1), "kind": "subwindow", **c}); cuts.append((c0, c1))
    out = [c for c in subtract(padded, cuts) if c[1] - c[0] > 0.02]
    return out, trans


def gain_grid(regions, dur, g):
    n = int(dur * GRID) + 2
    floor = 0.0 if str(g["attenuation_db"]).lower() in ("-inf", "inf", "none") else 10 ** (float(g["attenuation_db"]) / 20)
    on = np.zeros(n, bool)
    for a, b in regions:
        on[int(a * GRID):int(b * GRID) + 1] = True
    f = max(1, int(g["fade_ms"] * GRID / 1000))
    k = np.convolve(on.astype(float), np.ones(f) / f, mode="same")  # linear fades of fade_ms, centred on the edge
    k = np.maximum(k, on * 0.0)
    return floor + (1 - floor) * np.clip(k, 0, 1)


def apply_gain(x, gg, sr):
    y = np.empty_like(x); step = sr * 60
    for s0 in range(0, len(x), step):
        t = np.arange(s0, min(len(x), s0 + step)) / sr
        y[s0:s0 + len(t)] = x[s0:s0 + len(t)] * np.interp(t * GRID, np.arange(len(gg)), gg)
    return y


def bursts(x, sr, regions, g):
    """QA metric: energy bursts (transient_rise_db above the track's noise floor, 30 ms..transient_max_s)
    that lie outside the (padded) speech regions."""
    fr = int(0.01 * sr); m = len(x) // fr
    db = np.empty(m)
    for c0 in range(0, m, 100000):
        c1 = min(m, c0 + 100000)
        db[c0:c1] = 10 * np.log10(np.mean(x[c0 * fr:c1 * fr].reshape(c1 - c0, fr) ** 2, axis=1) + 1e-12)
    ref = np.percentile(db[db > -119], 10) if np.any(db > -119) else -120
    hot = db > max(ref, g["noise_floor_min_db"]) + g["transient_rise_db"]
    sp = np.zeros(m, bool)
    for a, b in regions:
        sp[int(a * 100):int(b * 100) + 1] = True
    n, i = 0, 0
    while i < m:
        if hot[i] and not sp[i]:
            j = i
            while j < m and hot[j] and not sp[j]: j += 1
            if 3 <= j - i <= g["transient_max_s"] * 100 * 2: n += 1
            i = j
        else:
            i += 1
    return n


def laugh_spans(words, markers):
    return [(w["start"], w["end"], s) for s, ws in words.items() for w in ws if any(m in w["text"] for m in markers)]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True); a = ap.parse_args()
    ep = Path(a.ep); cfg = load_cfg(ep); g = cfg["gate"]
    if not g.get("enabled"):
        print("gate disabled"); return
    import soundfile as sf
    from render import loop, roomtone
    vad = load(ep / "work/vad.json"); words = load(ep / "work/words.json"); cands = load(ep / "work/candidates.json")
    laughs = laugh_spans(words, cfg["text"]["laugh_markers"])
    spk = speakers(ep); src = {s: ep / "work/level" / f"{s}.wav" for s in spk}
    sr = sf.info(str(src[spk[0]])).samplerate; n = min(sf.info(str(p)).frames for p in src.values()); dur = n / sr
    regs, trans, grids = {}, {}, {}
    for s in spk:
        rd = lambda a_, b_, p=src[s]: sf.read(str(p), start=int(a_ * sr), stop=int(b_ * sr), dtype="float64")[0]
        fl = track_floor(sf.read(str(src[s]), frames=n, dtype="float64")[0], sr)
        regs[s], trans[s] = speech_regions(s, vad, words, cands, laughs, rd, sr, g, fl)
        grids[s] = gain_grid(regs[s], dur, g)
    allg = np.prod([1 - gg for gg in grids.values()], axis=0)  # 1 where every track is gated
    fill = g.get("fill_track") or spk[0]
    out = ep / "work/gate"; out.mkdir(parents=True, exist_ok=True)
    log = {"tracks": {}}
    for s in spk:
        x = sf.read(str(src[s]), frames=n, dtype="float64")[0]
        before = bursts(x, sr, regs[s], g)
        y = apply_gain(x, grids[s], sr)
        filled = 0.0
        if s == fill:
            tone, t0 = roomtone(x, sr, vad["speakers"][s], cfg["render"]["roomtone_s"], g["transient_rise_db"], g["noise_floor_min_db"])
            log["roomtone_source"] = {"track": s, "start_s": r(t0), "end_s": r(t0 + len(tone) / sr)}
            del x
            step = sr * 60
            for s0 in range(0, n, step):
                s1 = min(n, s0 + step); t = np.arange(s0, s1) / sr
                w = np.interp(t * GRID, np.arange(len(allg)), allg)
                if w.max() > 0:
                    y[s0:s1] += loop(tone, s1 - s0, sr, int(0.05 * sr)) * w
            filled = float(allg.sum() / GRID)
        else:
            del x
        after = bursts(y, sr, regs[s], g)
        sf.write(str(out / f"{s}.wav"), y, sr, subtype="FLOAT"); del y
        log["tracks"][s] = {"speech_s": r(sum(b - a for a, b in regs[s]), 1), "gated_s": r(dur - sum(b - a for a, b in regs[s]), 1),
                            "transients_classified": len(trans[s]), "transients_subwindow": sum(t.get("kind") == "subwindow" for t in trans[s]), "transients_edge": sum(t.get("kind") == "edge" for t in trans[s]), "nonspeech_bursts_before": before, "nonspeech_bursts_after": after,
                            "roomtone_fill_s": r(filled, 1)}
    log["nonspeech_bursts_before"] = sum(v["nonspeech_bursts_before"] for v in log["tracks"].values())
    log["nonspeech_bursts_after"] = sum(v["nonspeech_bursts_after"] for v in log["tracks"].values())
    dump(out / "regions.json", {"regions": regs, "transients": trans})
    dump(ep / "logs/gate.json", log)
    (out / ".done").touch()
    log_step(ep, "gate", {k: v for k, v in log.items() if k != "tracks"})
    print("gate", log)


if __name__ == "__main__":
    main()
