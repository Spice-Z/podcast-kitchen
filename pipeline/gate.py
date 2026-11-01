"""Step 5-pre: per-track speech gating (config `gate`). Runs after level, before render.

Each speaker track is muted (gate.attenuation_db; "-inf" = full mute) outside its own speech regions:
  speech = own Silero VAD islands  ∪  aligned transcript segments (status != rejected)  ∪  laughs  ∪  backchannel candidates,
  minus non-speech transients: VAD islands <= transient_max_s with no transcript text, no laugh/backchannel,
  and low voicing (autocorr peak 80-400 Hz < voicing_max) or high spectral flatness (> flatness_min) — sniffs, coughs,
  throat-clears. Regions are padded (pad_before_ms / pad_after_ms), gaps < merge_gap_ms merged, edges faded (fade_ms).
Room tone continuity: where every track is gated, the reference track (gate.fill_track) gets its own room tone
(render.roomtone) faded in, so the mix never drops to digital silence.
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


def speech_regions(s, vad, words, cands, laughs, read, sr, g):
    """-> (padded merged regions, transients list). read(a, b) returns the track samples for [a, b) seconds."""
    txt = [(w["start"], w["end"]) for w in words.get(s, []) if w.get("status") != "rejected"]
    keep = [(c["start"], c["end"]) for c in cands if c["type"] == "backchannel" and c["track"] == s] + \
           [(a, b) for a, b, t in laughs if t == s]
    sp, trans = list(txt) + keep, []
    for a, b in vad["speakers"][s]:
        if b - a <= g["transient_max_s"] and not any(overl(a, b, x, y) > 0 for x, y in txt + keep):
            c = classify(read(a, b), sr, g)
            if c["transient"]:
                trans.append({"start": r(a), "end": r(b), **c}); continue
        sp.append((a, b))
    pb, pa = g["pad_before_ms"] / 1000, g["pad_after_ms"] / 1000
    padded = merge([(max(0.0, a - pb), b + pa) for a, b in sp], g["merge_gap_ms"] / 1000)
    # a transient stays gated even when the pad of neighbouring speech reaches it: clip it back out
    out = []
    for a, b in padded:
        cur = [[a, b]]
        for t in trans:
            nxt = []
            for x, y in cur:
                if t["end"] <= x or t["start"] >= y or any(overl(t["start"], t["end"], p, q) > 0 for p, q in sp):
                    nxt.append([x, y]); continue
                if t["start"] > x: nxt.append([x, t["start"]])
                if t["end"] < y: nxt.append([t["end"], y])
            cur = nxt
        out += [c for c in cur if c[1] - c[0] > 0.02]
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
        regs[s], trans[s] = speech_regions(s, vad, words, cands, laughs, rd, sr, g)
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
            tone, _ = roomtone(x, sr, vad["speakers"][s], cfg["render"]["roomtone_s"])
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
                            "transients_classified": len(trans[s]), "nonspeech_bursts_before": before, "nonspeech_bursts_after": after,
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
