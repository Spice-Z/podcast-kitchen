"""Step 5a: mid-show jingle, inserted exactly ONCE (render stage: after render cuts, before ending_bgm/loudness).
Placement (edited time): a pause between sentences = a gap in the union of all speakers' VAD islands (>= jingle.min_gap_s,
not covered by any transcript segment, trailing laughter/aizuchi waited out (jingle.max_tail_s), outside the first
jingle.min_start_s and the last jingle.exclude_end_s / the ending-BGM search window).
 1) chapter boundaries (chapters_raw.json, mapped through the timemap; the opening chapter is ignored): the boundary
    closest to the episode midpoint wins; the insertion gap is the qualifying gap nearest it within
    [-jingle.chapter_before_s, +jingle.chapter_after_s];
 2) otherwise the longest qualifying gap with a speaker change across it (fallback: the longest gap).
The gap's silence [last speech end, next speech start] is replaced by pre_silence_s of digital silence + the jingle
(active level matched to the voices' active level over +-jingle.voice_ref_window_s, + jingle.gain_db) + post_silence_s,
with jingle.edge_fade_ms fades on the voice either side. No speech is removed; the episode gets longer by
pre + jingle + post - gap. timemap.json is spliced (spans after the gap shift, joins shift, edited_duration_s), so
chapters, ending BGM, show notes and QA all follow; timemap["jingle"] records the span. Re-runs restore
work/mix_prejingle.wav / work/timemap_prejingle.json first (never two jingles). Disabled / file missing / no
qualifying gap -> warning, unchanged. Log: logs/jingle.json."""
import argparse, os, re, shutil, subprocess, sys
from pathlib import Path
import numpy as np
from common import dump, load, load_cfg, log_step, r, speakers

DEF = {"enabled": True, "prefer_range_frac": [0.3, 0.7], "widen_step_frac": 0.1, "max_tail_s": 4.0, "speaker_change_bonus_s": 0.3, "react_max_s": 1.0, "file": "../../assets/jingle.mp3", "pre_silence_s": 0.4, "post_silence_s": 0.2, "gain_db": -2.0,
       "voice_ref_window_s": 60.0, "min_gap_s": 0.35, "min_start_s": 120.0, "exclude_end_s": 180.0, "chapter_before_s": 20.0,
       "chapter_after_s": 5.0, "avoid_margin_s": 1.0, "edge_fade_ms": 10.0, "segment_tolerance_s": 0.3,
       "track_shift": True, "max_shift_s": 3.0, "split_pad_s": 0.05, "own_silence_s": 0.3, "max_tail_overlap_s": 1.5,
       "shift_only_at_chapters": True}


LAUGH_BC = re.compile(r"^[ふはへひほあいうえおんそっーぁぃぅぇぉ〜、。！？!?\s]{1,8}$")   # laughs / short backchannels in text


def map_time(tm, t):
    for a, b, o in tm["spans"]:
        if t < a:
            return o
        if t <= b:
            return o + (t - a)
    a, b, o = tm["spans"][-1]
    return o + (b - a)


def merge(iv):
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


SENT_END = re.compile(r"(。|！|!|です|ます|でした|ました|ですね|ますね|ですよ|ますよ|よね|すね|かな|だね|だよ|気がする|と思う|かもしれない|だった)\s*$")  # no "?"
REPLY = re.compile(r"^(そう|うん|はい|ええ|なるほど|確かに|たしかに|いや)")   # next line answering/agreeing = same exchange


def gaps(islands, segs, avoid, lo, hi, min_gap, margin, tol=0.3, reactions=(), max_tail_s=4.0, react_max_s=1.0):
    """qualifying insertion gaps (start, end, speaker_change, tail_s) in edited time.
    islands: [(a, b, speaker)] VAD; segs: [(a, b[, text])] substantive transcript segments (no laughs/aizuchi);
    reactions: [(a, b)] laughter / backchannels / short reactions; avoid: [(a, b)] overlaps (rejected within margin).
    Candidate = end of substantive speech at a sentence end (SENT_END, not a question; next substantive line not a
    reply, REPLY; no segment running through, `tol` for ASR overhang). An island is a reaction if half of it lies in
    `reactions`, or it is <= react_max_s with no substantive segment on it. The insertion point waits out the reaction
    tail on any track until all tracks are quiet for >= min_gap (tail <= max_tail_s); if substantive speech starts
    first, the candidate is rejected. Nothing is cut."""
    isl = sorted(islands); rx = merge(list(reactions))
    def inter(a, b, iv):
        return sum(max(0.0, min(b, y) - max(a, x)) for x, y in iv)
    def is_react(a, b):
        if inter(a, b, rx) >= 0.5 * (b - a):
            return True
        return b - a <= react_max_s and not any(sg[0] < b - 0.05 and sg[1] > a + 0.05 for sg in segs)
    sub = [x for x in isl if not is_react(x[0], x[1])]
    us = merge([(a, b) for a, b, _ in sub]); ua = merge([(a, b) for a, b, _ in isl]); out = []
    for (a0, s_end), (n0, n1) in zip(us, us[1:]):
        if s_end < lo or s_end > hi:
            continue
        hole = next(((x1, y0) for (_, x1), (y0, _) in zip(ua, ua[1:]) if x1 >= s_end - 1e-6 and y0 - x1 >= min_gap), None)
        if hole is None or hole[0] - s_end > max_tail_s or hole[1] > n0 + 1e-6 or hole[1] > hi:
            continue                                   # tail too long, or new substantive speech before a clean pause
        g0, g1 = hole
        if any(sg[0] < g0 - tol and sg[1] > g1 + tol for sg in segs):
            continue
        prev = [sg for sg in segs if len(sg) > 2 and sg[1] <= g0 + tol]
        if prev and not SENT_END.search(max(prev, key=lambda sg: sg[1])[2]):
            continue
        nxt = [sg for sg in segs if len(sg) > 2 and sg[0] >= g1 - tol]
        if nxt and REPLY.match(min(nxt, key=lambda sg: sg[0])[2]):
            continue
        if any(s < g1 + margin and e > g0 - margin for s, e in avoid):
            continue
        before = max((x for x in sub if x[1] <= s_end + 1e-6), key=lambda x: x[1])[2]
        after = min((x for x in sub if x[0] >= n0 - 1e-6), key=lambda x: x[0])[2]
        out.append((g0, g1, before != after, round(g0 - s_end, 3)))
    return out


def shift_candidates(islands, segs, reactions, chapters, p, lo, hi):
    """track-shift candidates: the next speaker X starts (onset n0) before the others' trailing laughter / aizuchi /
    sentence tail has ended. X's track is split at sp = n0 - split_pad_s (X silent for own_silence_s before n0); the
    other tracks play their tails until all are quiet (T <= sp + max_shift_s); then pre / jingle / post; then every
    track resumes from the common point (X from sp, others from T: both land at T + insert). Rejected if another track
    starts substantive speech after sp, or a substantive line of another track runs more than max_tail_overlap_s past
    n0, or the text rules fail (sentence end before, no question, X's line not a reply / mid-sentence).
    -> [(T, T, True, tail_s, {"speaker": X, "split_s": sp, "quiet_s": T})]"""
    isl = sorted(islands); rx = merge(list(reactions)); out = []
    def inter(a, b, iv):
        return sum(max(0.0, min(b, y) - max(a, x)) for x, y in iv)
    def is_react(a, b):
        if inter(a, b, rx) >= 0.5 * (b - a):
            return True
        return b - a <= p["react_max_s"] and not any(sg[0] < b - 0.05 and sg[1] > a + 0.05 for sg in segs)
    tol = p["segment_tolerance_s"]
    for n0, n1, x in isl:
        if is_react(n0, n1) or not lo <= n0 <= hi:
            continue
        if p["shift_only_at_chapters"] and not any(c - p["chapter_before_s"] <= n0 <= c + p["chapter_after_s"] for c in chapters):
            continue
        sp = n0 - p["split_pad_s"]
        if any(s0 < n0 and s1 > n0 - p["own_silence_s"] for s0, s1, y in isl if y == x and (s0, s1) != (n0, n1)):
            continue                                            # X not silent right before its onset
        others = [(a, b, y) for a, b, y in isl if y != x and b > sp and a < sp + p["max_shift_s"] + 1.0]
        if not others:
            continue                                            # nobody to wait for: plain pause handles it
        T = max(b for a, b, _ in others)
        if T - sp > p["max_shift_s"]:
            continue
        bad = False
        for a, b, y in others:
            sub = not is_react(a, b)
            if sub and a >= sp:
                bad = True; break                               # someone else starts real speech: no
            if sub and b > n0 + p["max_tail_overlap_s"]:
                bad = True; break                               # X's onset overlaps another's ongoing line
        if bad or T > hi:
            continue
        # nobody starts again right after T (all quiet for min_gap)
        if any(y != x and T < a < T + p["min_gap_s"] for a, b, y in isl):
            continue
        prev = [sg for sg in segs if len(sg) > 2 and sg[1] <= T + tol and sg[0] < sp and (len(sg) < 4 or sg[3] != x or sg[1] <= sp + tol)]
        if prev and not SENT_END.search(max(prev, key=lambda sg: sg[1])[2]):
            continue
        mine = [sg for sg in segs if len(sg) > 2 and sg[0] >= sp - tol and (len(sg) < 4 or sg[3] == x)]
        if mine and REPLY.match(min(mine, key=lambda sg: sg[0])[2]):
            continue
        if any(sg[0] < sp - tol and sg[1] > n0 + tol and (len(sg) > 3 and sg[3] == x) for sg in segs):
            continue                                            # X mid-sentence
        out.append((round(T, 3), round(T, 3), True, round(T - sp, 3), {"speaker": x, "split_s": round(sp, 3), "quiet_s": round(T, 3)}))
    return out


def tiers(dur, p):
    """[(k, lo_s, hi_s)]: prefer_range_frac of the edited duration first, widened by widen_step_frac per tier
    until it covers the whole show (the hard min_start_s / exclude_end_s limits are applied by gaps())."""
    lo, hi = p.get("prefer_range_frac", [0.3, 0.7]); st = max(float(p.get("widen_step_frac", 0.1)), 1e-3)
    out, k = [], 0
    while True:
        a, b = max(0.0, lo - k * st), min(1.0, hi + k * st)
        out.append((k, a * dur, b * dur))
        if a <= 0 and b >= 1:
            return out
        k += 1


def choose(gs, chapters, dur, p):
    """-> (gap, reason). Tiered: candidates inside the preferred middle range first, widening stepwise;
    within a tier chapter boundary > natural pause."""
    for k, a, b in tiers(dur, p):
        g, why = choose_in([x for x in gs if a <= x[0] <= b], [c for c in chapters if a <= c <= b], dur, p)
        if g:
            return g, f"{why}; range tier {k} ({a / 60:.1f}-{b / 60:.1f} min)"
    return None, "no qualifying pause"


def choose_in(gs, chapters, dur, p):
    """-> (gap, reason). chapters: edited chapter starts (excluding the opening)."""
    mid = dur / 2
    for c in sorted(chapters, key=lambda c: abs(c - mid)):
        near = [g for g in gs if c - p["chapter_before_s"] <= g[1] and g[0] <= c + p["chapter_after_s"]]
        if near:
            g = min(near, key=lambda g: (abs(g[1] - c), -(g[1] - g[0])))
            how = (f"track-shift: {g[4]['speaker']} split at {g[4]['split_s']:.2f} s, others' tail waited {g[3]:.2f} s"
                   if len(g) > 4 and g[4] else "clean sentence-end pause")
            return g, f"chapter boundary at {c:.1f} s (closest to the episode midpoint; {how})"
    gs = [g for g in gs if not (len(g) > 4 and g[4])]          # track-shift only rescues chapter boundaries
    if not gs:
        return None, "no qualifying pause"
    g = max(gs, key=lambda g: g[1] - g[0] + p.get("speaker_change_bonus_s", 0.3) * bool(g[2]))
    return g, "no usable chapter boundary: longest sentence-end pause" + (" with a speaker change" if g[2] else "")


def splice(tm, s, e, length):
    """replace edited [s, e] (silence) by `length` s: spans/joins after e shift by length - (e - s)."""
    d = length - (e - s); spans = []
    for a, b, o in tm["spans"]:
        oe = o + (b - a)
        if oe <= s + 1e-9:
            spans.append([a, b, o]); continue
        if o >= e - 1e-9:
            spans.append([a, b, r(o + d, 6)]); continue
        if o < s:
            spans.append([a, r(a + (s - o), 6), o])
        if oe > e:
            spans.append([r(a + (e - o), 6), b, r(s + length, 6)])
    tm = dict(tm); tm["spans"] = spans
    tm["joins"] = [{**j, "out_s": r(j["out_s"] + d, 6)} if j["out_s"] >= e else j for j in tm.get("joins", [])]
    tm["edited_duration_s"] = r(tm["edited_duration_s"] + d, 6)
    return tm, d


def active_rms_db(x, sr):
    fr = int(0.05 * sr); m = len(x) // fr
    if m == 0:
        return -120.0
    e = np.mean(x[: m * fr].reshape(m, fr) ** 2, axis=1); db = 10 * np.log10(e + 1e-20)
    return float(10 * np.log10(np.mean(e[db > np.max(db) - 30]) + 1e-20))


def build_insert(jingle, sr, p, voice_db):
    """pre silence + level-matched jingle + post silence (mono)."""
    j = jingle * 10 ** ((voice_db + p["gain_db"] - active_rms_db(jingle, sr)) / 20)
    f = max(1, int(0.005 * sr)); j[:f] *= np.linspace(0, 1, f); j[-f:] *= np.linspace(1, 0, f)
    return np.concatenate([np.zeros(int(round(p["pre_silence_s"] * sr))), j, np.zeros(int(round(p["post_silence_s"] * sr)))])


def decode(path, sr):
    q = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f64le", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(q.stdout, np.float64).copy()


def plan(ep, p, tm, dur, at=None):
    words = load(ep / "work/words.json"); vad = load(ep / "work/vad.json")
    m = lambda t: map_time(tm, t)
    isl = [(m(a), m(b), s) for s in speakers(ep) for a, b in vad["speakers"][s] if m(b) > m(a)]
    segs = [(m(g["start"]), m(g["end"]), g.get("text", ""), s) for s in speakers(ep) for g in words.get(s, [])
            if g.get("status") != "rejected" and not LAUGH_BC.match(g.get("text", "").strip())]
    edits = load(ep / "work/edits.json") if (ep / "work/edits.json").exists() else []
    avoid = [(m(e["start"]), m(e["end"])) for e in edits if e["type"] in ("overlap_yield", "overlap_restart", "overlap_abandon", "mutual_yield")]
    react = [(m(e["start"]), m(e["end"])) for e in edits if e["type"] in ("backchannel", "laugh")]
    react += [(m(g["start"]), m(g["end"])) for s in speakers(ep) for g in words.get(s, []) if LAUGH_BC.match(g.get("text", "").strip())]
    eb = (load_cfg(ep).get("ending_bgm") or {})
    hi = dur - max(p["exclude_end_s"], eb.get("search_window_s", 0) if eb.get("enabled") else 0)
    gs = gaps(isl, segs, avoid, p["min_start_s"], hi, p["min_gap_s"], p["avoid_margin_s"], p["segment_tolerance_s"],
              react, p["max_tail_s"], p["react_max_s"])
    chs = []
    if (ep / "chapters_raw.json").exists():
        chs = [m(c["raw_s"]) for c in load(ep / "chapters_raw.json") if c["raw_s"] > 0]
    if p["track_shift"] and stems_ok(ep):
        gs = gs + shift_candidates(isl, segs, react, chs, p, p["min_start_s"], hi)
    if at is not None:
        if not gs:
            return None, "no qualifying pause"
        g = min(gs, key=lambda g: abs(g[0] - at))
        return g, f"forced near {at:.1f} s"
    return choose(gs, chs, dur, p)


def stems_ok(ep):
    return any((ep / "work/render").glob("*.wav"))


def main():
    import soundfile as sf
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True)
    ap.add_argument("--dry-run", action="store_true", help="only report the placement")
    ap.add_argument("--at", type=float, help="force the qualifying candidate nearest this edited time (s; trials/previews)")
    a = ap.parse_args()
    ep = Path(a.ep); p = {**DEF, **(load_cfg(ep).get("jingle") or {})}
    mix_p, pre_p = ep / "work/mix.wav", ep / "work/mix_prejingle.wav"
    tm_p, tm_pre = ep / "work/timemap.json", ep / "work/timemap_prejingle.json"
    tm = load(tm_p)
    if "jingle" in tm and not a.dry_run:          # derived mix/timemap from an earlier run: restore, never insert twice
        if not (pre_p.exists() and tm_pre.exists()):
            raise SystemExit("jingle: timemap already has a jingle but work/mix_prejingle.wav is gone; run render first")
        shutil.copy(tm_pre, tm_p); os.replace(pre_p, mix_p); tm = load(tm_p)

    def skip(msg):
        print(f"WARNING jingle: {msg}; skipped", file=sys.stderr)
        if not a.dry_run:
            dump(ep / "logs/jingle.json", {"applied": False, "reason": msg}); log_step(ep, "jingle", {"applied": False, "reason": msg})
    if not p["enabled"]:
        return skip("disabled")
    f = Path(p["file"]); f = f if f.is_absolute() else (ep / f).resolve()
    if not f.exists():
        return skip(f"jingle file not found: {p['file']}")
    dur = tm["edited_duration_s"]
    g, why = plan(ep, p, tm, dur, a.at)
    if g is None:
        return skip(why)
    info_v = sf.info(str(mix_p)) if mix_p.exists() else None
    sr = info_v.samplerate if info_v else 48000
    jg = decode(f, sr); length = p["pre_silence_s"] + len(jg) / sr + p["post_silence_s"]
    info = {"applied": not a.dry_run, "gap_start_s": r(g[0]), "gap_end_s": r(g[1]), "gap_s": r(g[1] - g[0]), "speaker_change": g[2],
            "reason": why, "jingle_start_s": r(g[0] + p["pre_silence_s"]), "jingle_s": r(len(jg) / sr), "inserted_s": r(length),
            "resume_s": r(g[0] + length), "shift_s": r(length - (g[1] - g[0])), "mode": "pause"}
    ts = g[4] if len(g) > 4 else None
    if ts:
        D = g[0] - ts["split_s"] + length
        info.update({"mode": "track_shift", "shifted_speaker": ts["speaker"], "split_s": ts["split_s"], "quiet_s": ts["quiet_s"],
                     "tail_waited_s": g[3], "shift_s": r(D), "track_shift_s": {"shifted": r(D), "others": r(D)},
                     "shifted_track_extra_delay_s": r(g[0] - ts["split_s"])})
    if a.dry_run:
        print("jingle (dry run)", info); return
    with sf.SoundFile(str(mix_p)) as src:
        n, ch = src.frames, src.channels
        i0, i1 = int(round(g[0] * sr)), int(round(g[1] * sr)); w = int(p["voice_ref_window_s"] * sr)
        src.seek(max(0, i0 - w)); ref = src.read(min(n, i1 + w) - max(0, i0 - w), dtype="float64", always_2d=True)[:, 0]
    vdb = active_rms_db(ref, sr); ins = build_insert(jg, sr, p, vdb)
    if ts:
        os.replace(mix_p, pre_p); shutil.copy(tm_p, tm_pre)
        try:
            write_track_shift(ep, mix_p, sr, ch, ts, g[0], ins, p)
        except BaseException:
            os.replace(pre_p, mix_p); tm_pre.unlink(); raise
        tm2, d = splice(tm, ts["split_s"], ts["split_s"], g[0] - ts["split_s"] + length)
        return finish(ep, tm_p, tm2, info, vdb, p)
    os.replace(mix_p, pre_p); shutil.copy(tm_p, tm_pre)
    fm = max(1, int(p["edge_fade_ms"] / 1000 * sr)); blk = sr * 60
    with sf.SoundFile(str(pre_p)) as src, sf.SoundFile(str(mix_p), "w", sr, ch, subtype="FLOAT") as dst:
        for s0 in range(0, i0, blk):
            y = src.read(min(blk, i0 - s0), dtype="float64", always_2d=True)
            if s0 + len(y) == i0:
                k = min(fm, len(y)); y[-k:] *= np.linspace(1, 0, k)[:, None]
            dst.write(y)
        dst.write(np.repeat(ins[:, None], ch, 1))
        src.seek(i1); first = True
        while True:
            y = src.read(blk, dtype="float64", always_2d=True)
            if not len(y):
                break
            if first:
                k = min(fm, len(y)); y[:k] *= np.linspace(0, 1, k)[:, None]; first = False
            dst.write(y)
    tm2, d = splice(tm, g[0], g[1], length)
    return finish(ep, tm_p, tm2, info, vdb, p)


def track_pieces(n, cut, resume, z):
    """one track: src[0:cut] + zeros(z) + src[resume:n] (sample indices)."""
    return [("src", 0, cut), ("zero", z), ("src", resume, n)]


def write_track_shift(ep, mix_p, sr, ch, ts, quiet_s, ins, p):
    """rebuild the mix from the per-track render stems: X = src[:sp] + 0(D) + src[sp:]; others = src[:T] + 0(D) + src[T:];
    D = T - sp + insert; the insert (pre / jingle / post) starts at T. Every track keeps all its samples."""
    import soundfile as sf
    stems = sorted((ep / "work/render").glob("*.wav"))
    i_sp, i_T = int(round(ts["split_s"] * sr)), int(round(quiet_s * sr)); L = len(ins); D = i_T - i_sp + L
    fm = max(1, int(p["edge_fade_ms"] / 1000 * sr))
    fs = [sf.SoundFile(str(f)) for f in stems]
    n = fs[0].frames
    plans = [track_pieces(n, i_sp, i_sp, D) if st.stem == ts["speaker"] else track_pieces(n, i_T, i_T, D) for st in stems]
    total = n + D; blk = sr * 30
    def render_block(f, pieces, o0, o1):
        y = np.zeros(o1 - o0); pos = 0
        for pc in pieces:
            ln = pc[2] - pc[1] if pc[0] == "src" else pc[1]
            a, b = max(o0, pos), min(o1, pos + ln)
            if a < b and pc[0] == "src":
                f.seek(pc[1] + a - pos); seg = f.read(b - a, dtype="float64", always_2d=True)[:, 0]
                k0, k1 = pc[1] + a - pos, pc[1] + b - pos        # fades at piece edges (split points), not at file edges
                if pc[1] > 0:
                    e = min(fm, pc[2] - pc[1]); w = np.arange(k0, k1) - pc[1]; m = w < e
                    seg[m] *= w[m] / e
                if pc[2] < n:
                    e = min(fm, pc[2] - pc[1]); w = pc[2] - 1 - np.arange(k0, k1); m = w < e
                    seg[m] *= w[m] / e
                y[a - o0:b - o0] = seg
            pos += ln
        return y
    with sf.SoundFile(str(mix_p), "w", sr, ch, subtype="FLOAT") as dst:
        for o0 in range(0, total, blk):
            o1 = min(total, o0 + blk); y = np.zeros(o1 - o0)
            for f, pcs in zip(fs, plans):
                y += render_block(f, pcs, o0, o1)
            a, b = max(o0, i_T), min(o1, i_T + L)
            if a < b:
                y[a - o0:b - o0] += ins[a - i_T:b - i_T]
            dst.write(np.repeat(y[:, None], ch, 1))
    for f in fs:
        f.close()


def finish(ep, tm_p, tm2, info, vdb, p):
    info.update({"voice_active_db": r(vdb, 1), "params": {k: p[k] for k in DEF if k != "file"}})
    tm2["jingle"] = {k: info[k] for k in ("gap_start_s", "jingle_start_s", "inserted_s", "resume_s", "shift_s", "mode")}
    if info["mode"] == "track_shift":           # raw time >= split maps +shift for every track (tails of the others
        tm2["jingle"].update({k: info[k] for k in ("shifted_speaker", "split_s", "quiet_s")})   # were played early)
        tm2["jingle"]["timeline_insert_s"] = info["shift_s"]
    dump(tm_p, tm2); dump(ep / "logs/jingle.json", info)
    log_step(ep, "jingle", {k: info[k] for k in ("jingle_start_s", "inserted_s", "shift_s")})
    print("jingle", {k: v for k, v in info.items() if k != "params"})


if __name__ == "__main__":
    main()
