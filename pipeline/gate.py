"""Step 5-pre: per-track speech gating (config `gate`). Runs after level, before render.

Each speaker track is muted (gate.attenuation_db; "-inf" = full mute) outside its own speech regions:
  speech = own Silero VAD islands  ∪  aligned transcript segments (status != rejected)  ∪  laughs  ∪  backchannel candidates,
  where word spans count only where they overlap own VAD islands (pads anchored to VAD edges, smear dropped),
  minus non-speech transients: VAD islands <= transient_max_s without firm text (a word mostly inside the island),
  no laugh/backchannel, and low voicing (autocorr peak 80-400 Hz < voicing_max) or high spectral flatness (> flatness_min) — sniffs, coughs,
  throat-clears; coughs/throat-clears that are low-band are caught by a separate burst rule (sudden onset from the
  noise floor + unstable pitch, no firm text, <= burst_max_s, >= burst_gap_s after own voiced speech); plus unvoiced energy bursts inside padded regions but outside voiced VAD (pad zones, merged gaps),
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


def highband(y, sr, hz=2000.0):
    """(share of spectral energy above hz, spectral centroid Hz)."""
    if len(y) < 16 or not np.any(y):
        return 0.0, 0.0
    p = np.abs(np.fft.rfft(y * np.hanning(len(y)))) ** 2 + 1e-20; f = np.fft.rfftfreq(len(y), 1 / sr)
    return float(p[f > hz].sum() / p.sum()), float((p * f).sum() / p.sum())


def classify(y, sr, g):
    """Sniff/cough/throat-clear = low periodicity AND noise-like high-band energy (share above 2 kHz > hb_share_min,
    or centroid > centroid_min_hz, or flatness > flatness_min). Breathy/creaky speech decays are low-voicing but
    low-band, so they are not transients."""
    v, fl = voicing(y, sr), flatness(y); hb, cen = highband(y, sr)
    noisy = hb > g.get("hb_share_min", 0.4) or cen > g.get("centroid_min_hz", 2000) or fl > g["flatness_min"]
    return {"voicing": r(v, 3), "flatness": r(fl, 4), "hb_share": r(hb, 3), "centroid_hz": r(cen, 0),
            "transient": bool(v < g["voicing_max"] and noisy)}


def windows(y, sr, g, step=0.1):
    """Per-window features over y (step s): list of dict(voicing, transient, db)."""
    n = max(1, int(round(len(y) / (step * sr)))); st = len(y) / n; out = []
    for i in range(n):
        w = y[int(i * st):int((i + 1) * st)]
        c = classify(w, sr, g); c["db"] = float(10 * np.log10(np.mean(w ** 2) + 1e-12)) if len(w) else -120.0
        c["voiced"] = c["voicing"] >= g["voicing_max"]; out.append(c)
    return out


def decaying(ws, i):
    """True when window i is part of a level run that keeps falling (<= +1 dB per step) from the nearest voiced window
    before it: a voiced decay (word-final vowel fading out), never muted."""
    j = i
    while j > 0 and not ws[j - 1]["voiced"]:
        j -= 1
    if j == 0:
        return False
    return all(ws[k]["db"] <= ws[k - 1]["db"] + 1.0 for k in range(j, i + 1))


def f0_track(y, sr, hop=0.02):
    """Per 20 ms frame: (f0 Hz, normalized autocorr peak 60-400 Hz)."""
    n = int(hop * sr); out = []
    for i in range(0, len(y) - n + 1, n):
        x = y[i:i + n] - y[i:i + n].mean()
        if not np.any(x):
            out.append((0.0, 0.0)); continue
        f = np.fft.rfft(x, 2 * n); ac = np.fft.irfft(f * np.conj(f))[:n]
        lo, hi = int(sr / 400), min(n - 1, int(sr / 60))
        k = lo + int(np.argmax(ac[lo:hi])); out.append((sr / k, float(ac[k] / (ac[0] + 1e-12))))
    return out


def burst(pre, y, sr, g, floor_db):
    """Cough / throat-clear (separate from the sniff rule, band-independent): sudden onset (level rises >= burst_onset_db
    within burst_onset_ms, starting within burst_floor_db of the noise floor; `pre` = the samples just before the island)
    AND unstable pitch (median frame voicing < burst_voicing_max, or median frame-to-frame f0 jump > burst_jump_max).
    -> feature dict with 'burst' bool."""
    db = frame_db(np.concatenate([pre, y]), sr); k = max(1, int(round(g.get("burst_onset_ms", 40) / 10)))
    near = floor_db + g.get("burst_floor_db", 10.0); rise = 0.0
    for j in range(k, len(db)):
        lo = db[j - k:j].min()
        if lo <= near: rise = max(rise, db[j] - lo)
    ft = f0_track(y, sr); ldb = frame_db(y, sr, 0.02)[:len(ft)]
    loud = [ft[i] for i in range(len(ft)) if ldb[i] > ldb.max() - 20] if len(ft) else []
    med_r = float(np.median([q for _, q in loud])) if loud else 0.0
    fs = [f for f, _ in loud]
    jump = float(np.median([abs(b - a) / a for a, b in zip(fs, fs[1:]) if a > 0])) if len(fs) > 1 else 1.0
    ok = rise >= g.get("burst_onset_db", 30.0) and (med_r < g.get("burst_voicing_max", 0.5) or jump > g.get("burst_jump_max", 0.15))
    return {"onset_rise_db": r(rise, 1), "median_voicing": r(med_r, 2), "f0_jump": r(jump, 2), "burst": bool(ok)}


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


def relative_burst(x, sr, islands, g, floor_db):
    """Per-track cough thresholds from the track's own levels (10 ms frames):
    onset = burst_onset_snr_frac x SNR (speech p50 - floor; speech = VAD frames above their own 20th percentile),
    start margin = clamp(non-speech p90 - floor, burst_floor_min_db, burst_floor_max_db) (non-speech = frames
    > burst_ns_margin_s away from any VAD island). -> dict to merge into the gate config."""
    db = frame_db(x, sr); n = len(db)
    near, sp = np.zeros(n, bool), np.zeros(n, bool); m = int(g.get("burst_ns_margin_s", 0.3) * 100)
    for a, b in islands:
        near[max(0, int(a * 100) - m):int(b * 100) + m] = True; sp[max(0, int(a * 100)):int(b * 100)] = True
    spd, ns = db[sp], db[~near]
    if len(spd) == 0 or len(ns) == 0:
        return {}
    spd = spd[spd > np.percentile(spd, 20)]
    snr = float(np.percentile(spd, 50)) - floor_db
    margin = float(np.clip(np.percentile(ns, 90) - floor_db, g.get("burst_floor_min_db", 10), g.get("burst_floor_max_db", 15)))
    return {"burst_onset_db": r(g.get("burst_onset_snr_frac", 0.4) * snr, 1), "burst_floor_db": r(margin, 1), "snr_db": r(snr, 1)}


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


def edge_tails(y, sr, g, thr, t0, keep_tail=None):
    """Sniff/breath glued onto the head/tail of a voiced VAD island: steps of 50 ms from each edge inward while the step
    is loud (> thr) AND a transient (low voicing + noise-like high band). A run >= edge_tail_min_s is returned minus
    edge_keep_s next to the speech (keep_tail overrides the tail-side keep, e.g. word_end_keep_s). A tail run whose
    level keeps falling from the voiced part is a voiced decay and is kept."""
    ws = windows(y, sr, g, 0.05) if len(y) >= int(0.1 * sr) else []
    n = len(ws); vmin, keep = g.get("edge_tail_min_s", 0.2), g.get("edge_keep_s", 0.05)
    kt = keep if keep_tail is None else keep_tail
    bad = lambda i: ws[i]["db"] > thr and ws[i]["transient"]
    out = []
    i = n - 1
    while i >= 0 and bad(i): i -= 1
    if (n - 1 - i) * 0.05 >= vmin and i >= 0 and not decaying(ws, n - 1):
        c0 = t0 + (i + 1) * 0.05 + kt
        if c0 < t0 + len(y) / sr: out.append((c0, t0 + len(y) / sr))
    j = 0
    while j < n and bad(j): j += 1
    if j * 0.05 >= vmin and j < n:
        out.append((t0, t0 + j * 0.05 - keep))
    return out


def inner_windows(y, sr, g, thr, t0):
    """Inside a voiced VAD island: 100 ms windows that are loud, transient (unvoiced + high-band), have no voiced window
    within +-surround_s, and are not a voiced decay -> (start, end) cuts."""
    ws = windows(y, sr, g, 0.1); st = len(y) / sr / max(1, len(ws)); k = max(1, int(round(g.get("surround_s", 0.1) / 0.1)))
    out = []
    for i, w in enumerate(ws):
        if w["db"] <= thr or not w["transient"] or decaying(ws, i):
            continue
        if any(ws[j]["voiced"] for j in range(max(0, i - k), min(len(ws), i + k + 1)) if j != i):
            continue
        out.append((t0 + i * st, t0 + (i + 1) * st))
    return merge(out, 0.0)


def speech_regions(s, vad, words, cands, laughs, read, sr, g, floor_db=None):
    """-> (padded merged regions, transients list). read(a, b) returns the track samples for [a, b) seconds.
    Transient = low voicing AND noise-like high band (classify). Laughs and backchannels (and their pads) are exempt.
    1. Word spans count only where they overlap own VAD islands (smear dropped); pads are anchored to VAD edges.
    2. A word is firm support for an island only if it lies mostly inside it AND the island is not mostly unvoiced
       (island_unvoiced_frac of 100 ms windows). Islands <= transient_max_s without firm text are classified whole;
       islands <= island_sniff_max_s that are mostly unvoiced and contain a transient window are muted whole.
    3. Inside every other island, 100 ms transient windows not surrounded by voiced speech are muted (inner_windows),
       and sniffs glued to island edges are muted (edge_tails); voiced decays are kept.
    4. Pad zones / merged gaps (inside regions, outside voiced VAD): energy bursts classified per sub-window; the first
       word_end_keep_s after a VAD end adjacent to a word end (|VAD end - word end| <= word_end_tol_s) is never muted."""
    isl = [(a, b) for a, b in vad["speakers"][s]]
    txt = [(w["start"], w["end"]) for w in words.get(s, []) if w.get("status") != "rejected"]
    keep = [(c["start"], c["end"]) for c in cands if c["type"] == "backchannel" and c["track"] == s] + \
           [(a, b) for a, b, t in laughs if t == s]
    if floor_db is None:
        floor_db = g["noise_floor_min_db"]
    thr = max(floor_db, g["noise_floor_min_db"]) + g["transient_rise_db"]
    ufrac, smax = g.get("island_unvoiced_frac", 0.6), g.get("island_sniff_max_s", 1.0)
    wkeep, wtol = g.get("word_end_keep_s", 0.2), g.get("word_end_tol_s", 0.15)
    sp, trans, voiced, cuts, protect = list(keep), [], [], [], []
    bmax, bgap = g.get("burst_max_s", 0.6), g.get("burst_gap_s", 0.2)
    # aligned word tokens (not smeared ones) that substantially cover an island -> it is a word (うん/あー/確かに), never a burst
    wl = g.get("burst_word_max_s", 1.5)
    toks = [(w["start"], w["end"]) for seg in words.get(s, []) if seg.get("status") != "rejected"
            for w in seg.get("words", []) if w.get("start") is not None and w.get("end") is not None and w["end"] - w["start"] <= wl]
    has_tok = lambda a, b: any(overl(a, b, x, y) >= 0.5 * min(y - x, b - a) > 0 for x, y in toks)
    last_voiced = -1e9
    for a, b in isl:
        if any(overl(a, b, x, y) > 0 for x, y in keep):
            sp.append((a, b)); voiced.append((a, b)); continue
        y = read(a, b); ws = windows(y, sr, g, 0.1)
        unv = float(np.mean([not w["voiced"] for w in ws])) if ws else 0.0
        firm = firm_text(a, b, txt) and unv < ufrac
        c = None
        if b - a <= g["transient_max_s"] and not firm:
            c = classify(y, sr, g)
        elif b - a <= smax and unv >= ufrac and any(w["transient"] and w["db"] > thr for w in ws):
            c = classify(y, sr, g); c["transient"] = True
        if c is None or not c["transient"]:
            if g.get("burst_enabled", True) and not firm and b - a <= bmax and a - last_voiced >= bgap \
                    and not has_tok(a, b) and voicing(y, sr) < g.get("burst_island_voicing_max", 0.6):
                bc = burst(read(max(0.0, a - 0.1), a), y, sr, g, floor_db)
                if bc["burst"]:
                    trans.append({"start": r(a), "end": r(b), "kind": "burst", "unvoiced_frac": r(unv, 2), **classify(y, sr, g), **bc})
                    continue
        if c is not None and c["transient"]:
            trans.append({"start": r(a), "end": r(b), "kind": "island", "unvoiced_frac": r(unv, 2), **c}); continue
        sp.append((a, b)); voiced.append((a, b)); last_voiced = b
        word_end = any(abs(b - we) <= wtol for _, we in txt)
        if word_end:
            protect.append((b, b + wkeep))
        if b - a > g["transient_max_s"]:
            for c0, c1 in edge_tails(y, sr, g, thr, a, wkeep if word_end else None) + inner_windows(y, sr, g, thr, a):
                cc = classify(read(c0, c1), sr, g)
                trans.append({"start": r(c0), "end": r(c1), "kind": "edge" if c1 >= b - 1e-6 or c0 <= a + 1e-6 else "inner", **cc})
                cuts.append((c0, c1))
    pb, pa = g["pad_before_ms"] / 1000, g["pad_after_ms"] / 1000
    padded = merge([(max(0.0, a - pb), b + pa) for a, b in sp], g["merge_gap_ms"] / 1000)
    padded = subtract(padded, [(t["start"], t["end"]) for t in trans if t["kind"] in ("island", "burst")
                               and not any(overl(t["start"], t["end"], p, q) > 0 for p, q in sp)])
    firm_iv = merge(subtract([list(v) for v in voiced], cuts) + [[max(0.0, a - pb), b + pa] for a, b in keep]
                    + [list(p) for p in protect], 0.0)
    sub = []
    for a, b in padded:
        for x, y in subtract([[a, b]], firm_iv):
            if y - x < 0.03: continue
            for h0, h1 in hot_runs(read(x, y), sr, thr, x):
                c0, c1 = max(x, h0 - 0.02), min(y, h1 + 0.02)
                c = classify(read(c0, c1), sr, g)
                if c["transient"]:
                    trans.append({"start": r(c0), "end": r(c1), "kind": "subwindow", **c}); sub.append((c0, c1))
    out = [c for c in subtract(padded, cuts + sub) if c[1] - c[0] > 0.02]
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
    regs, trans, grids, rel = {}, {}, {}, {}
    for s in spk:
        rd = lambda a_, b_, p=src[s]: sf.read(str(p), start=int(a_ * sr), stop=int(b_ * sr), dtype="float64")[0]
        fl = track_floor(sf.read(str(src[s]), frames=n, dtype="float64")[0], sr)
        gs, rel[s] = g, {}
        if g.get("burst_relative", True):
            rel[s] = relative_burst(sf.read(str(src[s]), frames=n, dtype="float64")[0], sr, vad["speakers"][s], g, fl)
            gs = {**g, **{k: v for k, v in rel[s].items() if k.startswith("burst_")}}
        regs[s], trans[s] = speech_regions(s, vad, words, cands, laughs, rd, sr, gs, fl)
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
                            "transients_classified": len(trans[s]), "transients_subwindow": sum(t.get("kind") == "subwindow" for t in trans[s]), "transients_edge": sum(t.get("kind") == "edge" for t in trans[s]), "transients_inner": sum(t.get("kind") == "inner" for t in trans[s]), "transients_burst": sum(t.get("kind") == "burst" for t in trans[s]), "nonspeech_bursts_before": before, "nonspeech_bursts_after": after,
                            "roomtone_fill_s": r(filled, 1), "burst_thresholds": rel[s]}
    log["nonspeech_bursts_before"] = sum(v["nonspeech_bursts_before"] for v in log["tracks"].values())
    log["nonspeech_bursts_after"] = sum(v["nonspeech_bursts_after"] for v in log["tracks"].values())
    dump(out / "regions.json", {"regions": regs, "transients": trans})
    dump(ep / "logs/gate.json", log)
    (out / ".done").touch()
    log_step(ep, "gate", {k: v for k, v in log.items() if k != "tracks"})
    print("gate", log)


if __name__ == "__main__":
    main()
