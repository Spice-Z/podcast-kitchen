"""Step 7: deterministic QA. Writes logs/qa.json + logs/qa.md, exits 1 if any hard check fails.
Hard: LUFS and true peak on WAV master and MP3; clicks at joins; head/tail silence; chapters valid;
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


def longest_silence(x, sr, thr_db=-50):
    fr = int(0.01 * sr); n = len(x) // fr
    db = 10 * np.log10(np.mean(x[: n * fr].reshape(n, fr) ** 2, axis=1) + 1e-12)
    best = cur = 0
    for q in db < thr_db:
        cur = cur + 1 if q else 0; best = max(best, cur)
    return best * 0.01


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True); a = ap.parse_args()
    ep = Path(a.ep); cfg = load_cfg(ep); q = cfg["qa"]; L = cfg["loudness"]; slug = load(ep / "manifest.json")["slug"]
    res, fails = {}, []
    for k, p in (("wav", ep / "out" / f"{slug}_master.wav"), ("mp3", ep / "out" / f"{slug}.mp3")):
        i, tp = ebur(p)
        ok = abs(i - L["target_lufs"]) <= q["lufs_tolerance"] and tp <= L["max_true_peak_dbtp"]
        res[f"loudness_{k}"] = {"lufs": i, "true_peak_dbtp": tp, "pass": bool(ok)}
        if not ok: fails.append(f"loudness_{k}")
    x, sr = read_wav(ep / "out" / f"{slug}_master.wav"); x = x[:, 0] if x.ndim > 1 else x
    tm = load(ep / "work/timemap.json"); half = q["clip_s"] / 2
    joins = []
    for n, jn in enumerate(tm["joins"]):
        i = int(jn["out_s"] * sr)
        s0, s1 = max(0, i - int(half * sr)), min(len(x), i + int(half * sr))
        write_wav(ep / "work/qa" / f"cut_{n:03d}.wav", x[s0:s1], sr, subtype="PCM_24")
        ratio, mx = click_score(x, i, sr)
        fr = int(0.05 * sr)
        lv = lambda y: 10 * np.log10(np.mean(y ** 2) + 1e-12)
        jump = abs(lv(x[i - fr:i]) - lv(x[i:i + fr]))
        click = ratio > q["click_ratio"] and mx > q["click_min_abs"]
        joins.append({"n": n, "out_s": jn["out_s"], "ids": jn["ids"], "click_ratio": r(ratio, 2), "max_step": r(mx, 4),
                      "click": bool(click), "level_jump_db": r(jump, 1), "level_jump_flag": bool(jump > q["level_jump_db"])})
        if click: fails.append(f"click@{jn['out_s']}")
    res["joins"] = joins
    hs = int(q["head_tail_s"] * sr)
    head, tail = longest_silence(x[:hs], sr), longest_silence(x[-hs:], sr)
    res["head_tail"] = {"head_longest_silence_s": r(head, 2), "tail_longest_silence_s": r(tail, 2),
                        "pass": bool(head <= q["head_tail_max_silence_s"] and tail <= q["head_tail_max_silence_s"])}
    if not res["head_tail"]["pass"]: fails.append("head_tail")
    edits = load(ep / "work/edits.json"); vad = load(ep / "work/vad.json")
    lp = [e for e in edits if e["type"] == "long_pause"]
    lp_applied = [e for e in lp if e["approved"] and e["action"] == "cut"]
    u = [(map_time(tm, s), map_time(tm, e)) for s, e in vad["union"]]
    gaps = [b0 - a1 for (a0, a1), (b0, b1) in zip(u, u[1:])]
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
    res["sync"] = load(ep / "logs/sync.json")
    res["fails"] = fails; res["pass"] = not fails
    dump(ep / "logs/qa.json", res)
    md = [f"# QA {slug}: {'PASS' if not fails else 'FAIL'}", ""]
    for k in ("loudness_wav", "loudness_mp3"):
        v = res[k]; md.append(f"- {k}: {v['lufs']} LUFS, {v['true_peak_dbtp']} dBTP -> {'pass' if v['pass'] else 'FAIL'}")
    md.append(f"- joins: {len(joins)}, clicks: {sum(j['click'] for j in joins)}, level-jump flags: {sum(j['level_jump_flag'] for j in joins)}")
    md.append(f"- head/tail longest silence: {res['head_tail']['head_longest_silence_s']} / {res['head_tail']['tail_longest_silence_s']} s")
    md.append(f"- long_pause: {res['long_pause']}")
    md.append(f"- edits: {res['edits']}")
    md.append(f"- removed total: {tm['removed_s']} s; chapters: {len(ch)}")
    md.append(f"- review items pending: {sum(1 for e in edits if e['action']=='review' or not e['approved'] and e['action']!='keep')}")
    (ep / "logs/qa.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
