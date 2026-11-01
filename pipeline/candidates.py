"""Step 4a: deterministic rule candidates -> work/candidates.json (raw seconds, after sync).

Types (config.candidates, config.text): long_pause, filler, backchannel, overlap_yield, false_start,
crosstalk, mistake. Every candidate carries `default_action` from a measurable proxy; anything the
rules cannot decide is `review`. Timeline cuts use track 'all'; duck/mute act on one track only."""
import argparse
from pathlib import Path
from common import dump, key, load, load_cfg, log_step, speakers, r

TIMELINE = "all"


def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def speech(isl, t0, t1):
    return sum(overlap(s, e, t0, t1) for s, e in isl)


def norm(s):
    return s.replace("〜", "ー").replace("~", "ー").strip("、。!?！？ ")


class Ctx:
    def __init__(self, vad, words, cfg):
        self.vad, self.words, self.cfg = vad, words, cfg
        self.c, self.t = cfg["candidates"], cfg["text"]
        self.dur = vad["duration_s"]
        self.spk = sorted(vad["speakers"])
        self.segs = sorted(((g["start"], g["end"], s, g) for s in self.spk for g in words.get(s, [])), key=lambda x: (x[0], x[2]))
        self.laughs = self._laughs()

    def others(self, spk, t0, t1):
        return sum(speech(self.vad["speakers"][o], t0, t1) for o in self.spk if o != spk)

    def context(self, t0, t1):
        cs = self.c["context_s"]
        return " / ".join(f"{s}: {g['text']}" for a, b, s, g in self.segs if b >= t0 - cs and a <= t1 + cs)

    def excerpt(self, spk, t0, t1):
        segs = [g for a, b, s, g in self.segs if (spk in (s, TIMELINE)) and overlap(a, b, t0 - 0.05, t1 + 0.05) > 0]
        return " ".join(g["text"] for g in segs)[:80]

    def _laughs(self):
        """Laugh proxy: text markers, or short VAD islands with no aligned text (laugh/backchannel/filler)."""
        z = []
        for a, b, s, g in self.segs:
            if any(m in g["text"] for m in self.t["laugh_markers"]):
                z.append((a, b, s, "text"))
        for s in self.spk:
            for a, b in self.acoustic(s):
                z.append((a, b, s, "acoustic"))
        return sorted(z)

    def acoustic(self, s):
        """Short VAD islands with no ASR text, or covered only by aligner-rejected segments."""
        out = []
        for a, b in self.vad["speakers"][s]:
            if b - a > self.c["acoustic_island_max_s"]:
                continue
            txt = [g for g in self.words.get(s, []) if g["status"] != "rejected" and overlap(g["start"], g["end"], a, b) > 0]
            if not txt:
                out.append((a, b))
        return out

    def near_laugh(self, t0, t1, pad):
        return any(overlap(a, b, t0 - pad, t1 + pad) > 0 for a, b, _, k in self.laughs if k == "text")

    def protected_edge(self, t0, t1):
        p = self.c["protect_head_tail_s"]
        return t0 < p or t1 > self.dur - p


def cand(ctx, typ, track, t0, t1, action, reason, conf):
    ex = ctx.excerpt(track, t0, t1)
    con = ctx.context(t0, t1)
    return {"key": key(typ, track, r(t0), r(t1), ex, con), "type": typ, "track": track, "start": r(t0), "end": r(t1),
            "default_action": action, "reason": reason, "excerpt": ex, "context": con, "confidence": r(conf, 2)}


def long_pauses(ctx):
    lp = ctx.c["long_pause"]; u = ctx.vad["union"]; out = []
    for (a0, g0), (g1, b1) in zip(u, u[1:]):
        gap = g1 - g0
        prev = max(ctx.spk, key=lambda s: max([e for s0, e in ctx.vad["speakers"][s] if e <= g0 + 1e-6] or [-1]))
        nxt = min(ctx.spk, key=lambda s: min([s0 for s0, e in ctx.vad["speakers"][s] if s0 >= g1 - 1e-6] or [1e9]))
        thr = lp["within_turn_min_s"] if prev == nxt else lp["between_speakers_min_s"]
        if gap <= thr:
            continue
        h = lp["target_s"] / 2
        t0, t1 = g0 + h, g1 - h
        after = [z for z in ctx.laughs if g1 - 0.05 <= z[0] <= g1 + lp["laugh_lookahead_s"]]
        if after:
            act, why = "review", f"gap {gap:.2f}s followed by possible laugh/reaction ({after[0][3]}) -> possible punchline pause"
        else:
            act, why = "cut", f"gap {gap:.2f}s ({'within turn' if prev == nxt else 'speaker change'}) -> {lp['target_s']}s"
        out.append(cand(ctx, "long_pause", TIMELINE, t0, t1, act, why, 0.9))
    return out


def fillers(ctx):
    out = []; iso = ctx.c["filler_isolation_s"]; fl = set(ctx.t["fillers"])
    for s in ctx.spk:
        for g in ctx.words.get(s, []):
            ws = g["words"]
            for i, w in enumerate(ws):
                if w["start"] is None or w["pos"] not in ctx.t["filler_pos"] or norm(w["surface"]) not in fl:
                    continue
                prev_end = max([x["end"] for x in ws[:i] if x["end"] is not None] or [g["start"] - 1])
                next_start = min([x["start"] for x in ws[i + 1:] if x["start"] is not None] or [g["end"] + 1])
                if w["start"] - prev_end < iso or next_start - w["end"] < iso:
                    continue  # embedded in running speech: cutting would change rhythm
                t0, t1 = w["start"], w["end"]
                if g["status"] != "ok" or (w["score"] or 0) < ctx.cfg["align"]["min_word_score"]:
                    act, why = "review", f"filler '{w['surface']}' but alignment score low"
                elif ctx.protected_edge(t0, t1) or ctx.near_laugh(t0, t1, ctx.c["laugh_protect_s"]):
                    act, why = "review", "filler in protected head/tail or near laugh"
                elif ctx.others(s, t0, t1) > 0:
                    out.append(cand(ctx, "filler", s, t0, t1, "mute", f"filler '{w['surface']}' over other speech -> mute own track", w["score"])); continue
                else:
                    act, why = "cut", f"isolated filler '{w['surface']}' ({w['pos']})"
                out.append(cand(ctx, "filler", TIMELINE if act == "cut" else s, t0, t1, act, why, w["score"] or 0))
    return out


def backchannels(ctx):
    out = []; bc = set(ctx.t["backchannels"]); last = {}
    for s in ctx.spk:
        for g in ctx.words.get(s, []):
            toks = [norm(w["surface"]) for w in g["words"]]
            if not toks or g["end"] - g["start"] > ctx.c["backchannel_max_s"]:
                continue
            if not (norm(g["text"]) in bc or all(t in bc or t in ("うん", "はい", "そう") for t in toks)):
                continue
            t0, t1 = g["start"], g["end"]
            if ctx.others(s, t0, t1) < 0.5 * (t1 - t0):
                continue  # not over someone else's speech: it is a turn, not a backchannel
            if ctx.near_laugh(t0, t1, ctx.c["laugh_protect_s"]):
                act, why = "keep", "reaction near laugh"
            elif t0 - last.get(s, -1e9) >= ctx.c["backchannel_keep_every_s"]:
                act, why = "keep", f"first backchannel in {ctx.c['backchannel_keep_every_s']}s window"
                last[s] = t0
            elif g["status"] != "ok":
                act, why = "review", "excess backchannel, alignment score low"
            else:
                act, why = "duck", f"excess backchannel -> duck {ctx.cfg['render']['duck_db']} dB on own track"
            out.append(cand(ctx, "backchannel", s, t0, t1, act, why, g["score"]))
    # acoustic: speech islands with no aligned text (kotoba drops fillers/相槌) -> review only
    for s in ctx.spk:
        for a, b in ctx.acoustic(s):
            typ = "backchannel" if ctx.others(s, a, b) > 0.5 * (b - a) else "filler"
            out.append(cand(ctx, typ, s, a, b, "review", "acoustic: VAD speech with no aligned text (could be laugh)", 0.3))
    return out


def overlap_yield(ctx):
    """Two onsets within overlap_onset_s; the yielder (turn start: silent >= yield_pre_silence_s before) stops within
    yield_max_s while the other keeps >= continue_min_s of speech. Only the yielder's own track is muted, and only
    when the yielder then says a yield marker (どうぞ/ごめん...); otherwise review (it may be a finished phrase)."""
    out = []; c = ctx.c; bc = set(ctx.t["backchannels"]); marks = ctx.t["yield_markers"]
    V = ctx.vad["speakers"]
    for y in ctx.spk:
        prev_end = -1e9
        for a0, a1 in V[y]:
            pre, prev_end = a0 - prev_end, a1
            if a1 - a0 > c["yield_max_s"] or pre < c["yield_pre_silence_s"]:
                continue
            txt = ctx.excerpt(y, a0, a1)
            if not txt or norm(txt) in bc or any(m in txt for m in marks):
                continue
            for k in ctx.spk:
                if k == y:
                    continue
                hit = [(b0, b1) for b0, b1 in V[k] if abs(b0 - a0) <= c["overlap_onset_s"]]
                if not hit or speech(V[k], hit[0][0], hit[0][0] + c["continue_window_s"]) < c["continue_min_s"]:
                    continue
                after = ctx.excerpt(y, a1, a1 + c["yield_marker_window_s"])
                marked = any(m in after for m in marks)
                prot = ctx.protected_edge(a0, a1) or ctx.near_laugh(a0, a1, c["laugh_protect_s"])
                act = "mute" if marked and not prot else "review"
                why = (f"{y} yields to {k} (onsets {abs(hit[0][0]-a0):.2f}s apart" + (", then yield marker" if marked else ", no yield marker")
                       + f"); only {y}'s aborted phrase on {y}'s track")
                out.append(cand(ctx, "overlap_yield", y, a0, a1, act, why, 0.8 if marked else 0.4))
                break
    return out


def false_starts(ctx):
    out = []; c = ctx.c
    global BC_FL
    BC_FL = set(ctx.t["backchannels"]) | set(ctx.t["fillers"]) | {"うん", "はい", "そう"}
    for s in ctx.spk:
        ws = [w for g in ctx.words.get(s, []) if g["status"] == "ok" for w in g["words"] if w["start"] is not None and w["kana"]]
        i = 0
        while i < len(ws):
            hit = None
            for n in (3, 2):
                if i + n > len(ws):
                    continue
                k1 = "".join(w["kana"] for w in ws[i:i + n])
                if len(k1) < c["false_start_min_kana"]:
                    continue
                if all(norm(w["surface"]) in BC_FL for w in ws[i:i + n]):
                    continue  # repeated はい/うん/えー is not a false start
                for j in range(i + n, min(len(ws), i + n + 3)):  # restart within 2 words of the attempt
                    if ws[j]["start"] - ws[i]["start"] > c["false_start_window_s"]:
                        break
                    if "".join(w["kana"] for w in ws[j:j + n]) == k1 and ws[j]["start"] - ws[i + n - 1]["end"] < 1.5:
                        hit = (ws[i]["start"], ws[j]["start"]); break
                if hit:
                    break
            if hit:
                t0, t1 = hit
                tl = ctx.others(s, t0, t1) == 0 and not ctx.protected_edge(t0, t1) and not ctx.near_laugh(t0, t1, c["laugh_protect_s"])
                out.append(cand(ctx, "false_start", TIMELINE if tl else s, t0, t1, "cut" if tl else "review",
                                "repeated phrase within window; first attempt", 0.5))
                i = next((m for m, w in enumerate(ws) if w["start"] >= t1), len(ws))
            else:
                i += 1
    return out


def crosstalk(ctx):
    out = []; V = ctx.vad["speakers"]
    for i, a in enumerate(ctx.spk):
        for b in ctx.spk[i + 1:]:
            for a0, a1 in V[a]:
                for b0, b1 in V[b]:
                    o0, o1 = max(a0, b0), min(a1, b1)
                    if o1 - o0 >= ctx.c["crosstalk_min_overlap_s"]:
                        out.append(cand(ctx, "crosstalk", TIMELINE, o0, o1, "review", f"{a}+{b} overlap {o1-o0:.1f}s", 0.5))
    return out


def mistakes(ctx):
    return [cand(ctx, "mistake", TIMELINE, a, b, "review", "edit marker phrase", 0.5)
            for a, b, s, g in ctx.segs if any(m in g["text"] for m in ctx.t["mistake_markers"])]


def build(vad, words, cfg):
    ctx = Ctx(vad, words, cfg)
    cs = long_pauses(ctx) + fillers(ctx) + backchannels(ctx) + overlap_yield(ctx) + false_starts(ctx) + crosstalk(ctx) + mistakes(ctx)
    seen, out = set(), []
    for c in sorted(cs, key=lambda c: (c["start"], c["type"], c["track"], c["end"])):
        if c["key"] not in seen:
            seen.add(c["key"]); out.append(c)
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True); a = ap.parse_args()
    ep = Path(a.ep); cfg = load_cfg(ep)
    cs = build(load(ep / "work/vad.json"), load(ep / "work/words.json"), cfg)
    dump(ep / "work/candidates.json", cs)
    stats = {}
    for c in cs:
        stats.setdefault(c["type"], {}).setdefault(c["default_action"], 0)
        stats[c["type"]][c["default_action"]] += 1
    log_step(ep, "candidates", stats)
    print("candidates", stats)


if __name__ == "__main__":
    main()
