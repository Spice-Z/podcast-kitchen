"""Step 7: deterministic QA. Writes logs/qa.json + logs/qa.md, exits 1 if any hard check fails.
Hard: LUFS and true peak on the MP3 (the only deliverable); clicks at joins (MP3 decoded to a temp WAV, deleted);
edge (leading/trailing) silence <= edge_max_silence_s; head/tail silence; chapters valid;
sync confidence logged. Info: level jumps at joins, long_pause stats (count, removed, longest remaining gap)."""
import argparse, re, subprocess
from pathlib import Path
import numpy as np
from common import dump, load, load_cfg, read_wav, write_wav, r
from render import map_time


def ebur(path):
    p = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True)
    s = p.stderr[p.stderr.rfind("Summary:"):]
    return float(re.search(r"I:\s+(-?[\d.]+) LUFS", s).group(1)), float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", s).group(1))


def click_score(x, i, sr):
    d = np.abs(np.diff(x))
    j = int(0.002 * sr); w = int(0.05 * sr)
    near = d[max(0, i - j):i + j]
    ctx = np.concatenate([d[max(0, i - w):max(0, i - j)], d[i + j:i + w]])
    med = float(np.median(ctx)) if len(ctx) else 1e-9
    return float(near.max()) / max(med, 1e-9), float(near.max())


def click_score_bed(x, i, sr):
    """join step vs the 99.9th pct |diff| over +-0.5 s: under a music bed the median is no baseline (beats/attacks)."""
    d = np.abs(np.diff(x)); j = int(0.002 * sr); w = int(0.5 * sr)
    near = d[max(0, i - j):i + j]
    ctx = np.concatenate([d[max(0, i - w):max(0, i - j)], d[i + j:i + w]])
    return float(near.max()) / max(float(np.percentile(ctx, 99.9)) if len(ctx) else 1e-9, 1e-9)


def longest_silence(x, sr, thr_db=-50):
    fr = int(0.01 * sr); n = len(x) // fr
    db = 10 * np.log10(np.mean(x[: n * fr].reshape(n, fr) ** 2, axis=1) + 1e-12)
    best = cur = 0
    for q in db < thr_db:
        cur = cur + 1 if q else 0; best = max(best, cur)
    return best * 0.01


def edge_silence(x, sr, thr_db=-50):
    fr = int(0.01 * sr); n = len(x) // fr
    db = 10 * np.log10(np.mean(x[: n * fr].reshape(n, fr) ** 2, axis=1) + 1e-12)
    loud = np.nonzero(db >= thr_db)[0]
    return (loud[0] if len(loud) else n) * 0.01


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True); a = ap.parse_args()
    ep = Path(a.ep); cfg = load_cfg(ep); q = cfg["qa"]; L = cfg["loudness"]; slug = load(ep / "manifest.json")["slug"]
    res, fails = {}, []
    for k, p in (("mp3", ep / "out" / f"{slug}.mp3"),):
        i, tp = ebur(p)
        ok = abs(i - L["target_lufs"]) <= q["lufs_tolerance"] and tp <= L["max_true_peak_dbtp"]
        res[f"loudness_{k}"] = {"lufs": i, "true_peak_dbtp": tp, "pass": bool(ok)}
        if not ok: fails.append(f"loudness_{k}")
    tmp = ep / "work/qa/decoded.tmp.wav"; tmp.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(ep / "out" / f"{slug}.mp3"), "-ac", "1", "-c:a", "pcm_f32le", str(tmp)], check=True)
    x, sr = read_wav(tmp); tmp.unlink(); x = x[:, 0] if x.ndim > 1 else x
    tm = load(ep / "work/timemap.json"); half = q["clip_s"] / 2
    joins = []; bgm = tm.get("ending_bgm") if (tm.get("ending_bgm") or {}).get("applied") else None
    for n, jn in enumerate(tm["joins"]):
        i = int(jn["out_s"] * sr)
        s0, s1 = max(0, i - int(half * sr)), min(len(x), i + int(half * sr))
        if q.get("write_clips"): write_wav(ep / "work/qa" / f"cut_{n:03d}.wav", x[s0:s1], sr, subtype="PCM_24")
        ratio, mx = click_score(x, i, sr)
        fr = int(0.05 * sr)
        lv = lambda y: 10 * np.log10(np.mean(y ** 2) + 1e-12) if len(y) else 0.0
        jump = abs(lv(x[i - fr:i]) - lv(x[i:i + fr]))
        click = ratio > q["click_ratio"] and mx > q["click_min_abs"]
        if click and bgm and bgm["fade_in_start_s"] <= jn["out_s"] <= bgm["end_s"]:   # under the ending BGM bed
            ratio = click_score_bed(x, i, sr); click = ratio > q.get("click_ratio_bgm", 2.5)
        joins.append({"n": n, "out_s": jn["out_s"], "ids": jn["ids"], "click_ratio": r(ratio, 2), "max_step": r(mx, 4),
                      "click": bool(click), "level_jump_db": r(jump, 1), "level_jump_flag": bool(jump > q["level_jump_db"])})
        if click: fails.append(f"click@{jn['out_s']}")
    res["joins"] = joins
    hs = int(q["head_tail_s"] * sr)
    # with the ending BGM the deliberate fade-out + end_silence_s is the end; tail/edge checks stop at the fade start
    xe = x[:int(bgm["tail_end_s"] * sr)] if bgm and "tail_end_s" in bgm else x
    head, tail = longest_silence(x[:hs], sr), longest_silence(xe[-hs:], sr)
    res["head_tail"] = {"head_longest_silence_s": r(head, 2), "tail_longest_silence_s": r(tail, 2),
                        "pass": bool(head <= q["head_tail_max_silence_s"] and tail <= q["head_tail_max_silence_s"])}
    if not res["head_tail"]["pass"]: fails.append("head_tail")
    lead, trail = edge_silence(x, sr), edge_silence(xe[::-1], sr)
    res["edge_silence"] = {"lead_s": r(lead, 2), "trail_s": r(trail, 2), "pass": bool(max(lead, trail) <= q["edge_max_silence_s"])}
    if not res["edge_silence"]["pass"]: fails.append("edge_silence")
    edits = load(ep / "work/edits.json"); vad = load(ep / "work/vad.json")
    lp = [e for e in edits if e["type"] == "long_pause"]
    lp_applied = [e for e in lp if e["approved"] and e["action"] == "cut"]
    u = [(map_time(tm, s), map_time(tm, e)) for s, e in vad["union"]]
    jg = tm.get("jingle")   # the inserted pre-silence + jingle + post-silence is intentional, not a pause
    gaps = [b0 - a1 - (jg.get("timeline_insert_s", jg["inserted_s"]) if jg and a1 <= jg["jingle_start_s"] <= b0 else 0) for (a0, a1), (b0, b1) in zip(u, u[1:])]
    res["long_pause"] = {"candidates": len(lp), "applied": len(lp_applied), "review": sum(e["action"] == "review" for e in lp),
                         "removed_s": r(sum(j["raw_cut"][1] - j["raw_cut"][0] for j in tm["joins"] if any(e["id"] in j["ids"] for e in lp_applied)), 2),
                         "longest_remaining_gap_s": r(max(gaps) if gaps else 0, 2)}
    from collections import Counter
    res["edits"] = {f"{t}/{a}/{'approved' if ok else 'pending'}": n for (t, a, ok), n in
                    sorted(Counter((e["type"], e["action"], e["approved"]) for e in edits).items())}
    res["removed_total_s"] = tm["removed_s"]
    ch = load(ep / "out/chapters.json")["chapters"]; dur = len(x) / sr
    okc = ch[0]["startTime"] == 0 and all(c["startTime"] < dur for c in ch)
    res["chapters"] = {"n": len(ch), "pass": okc}
    if not okc: fails.append("chapters")
    if jg:
        res["jingle"] = jg
    res["sync"] = load(ep / "logs/sync.json")
    res["fails"] = fails; res["pass"] = not fails
    md = [f"# QA {slug}: {'PASS' if not fails else 'FAIL'}", ""]
    for k in ("loudness_mp3",):
        v = res[k]; md.append(f"- {k}: {v['lufs']} LUFS, {v['true_peak_dbtp']} dBTP -> {'pass' if v['pass'] else 'FAIL'}")
    md.append(f"- joins: {len(joins)}, clicks: {sum(j['click'] for j in joins)}, level-jump flags: {sum(j['level_jump_flag'] for j in joins)}")
    md.append(f"- edge silence lead/trail: {res['edge_silence']['lead_s']} / {res['edge_silence']['trail_s']} s (max {q['edge_max_silence_s']})")
    md.append(f"- head/tail longest silence: {res['head_tail']['head_longest_silence_s']} / {res['head_tail']['tail_longest_silence_s']} s")
    gl = ep / "logs/gate.json"
    if gl.exists():
        gj = load(gl); res["gate"] = {k: v for k, v in gj.items()}
        md.append(f"- gate: non-speech bursts before/after: {gj['nonspeech_bursts_before']} / {gj['nonspeech_bursts_after']}; "
                  + ", ".join(f"{s} {v['nonspeech_bursts_before']}->{v['nonspeech_bursts_after']} (transients {v['transients_classified']})" for s, v in gj['tracks'].items()))
    md.append(f"- long_pause: {res['long_pause']}")
    md.append(f"- edits: {res['edits']}")
    md.append(f"- removed total: {tm['removed_s']} s; chapters: {len(ch)}")
    md.append(f"- review items pending: {sum(1 for e in edits if e['action']=='review' or not e['approved'] and e['action']!='keep')}")
    import show_notes as SN
    pk = SN.package(ep); res["handoff"] = pk
    md.append(f"- handoff package: missing {pk['missing'] or 'none'} (show notes copied to out/: {pk['notes_copied']}); default publish {pk['publish_at_jst']} = {pk['publish_at_pt']}")
    dump(ep / "logs/qa.json", res)
    (ep / "logs/qa.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
