"""Step 6: chapters from the WAV master + timemap.json (no re-ASR).
Input: <ep>/chapters_raw.json [{"raw_s": float, "title": str}] written by the agent from the raw
transcript (titles confirmed by a human); if absent a single 00:00 chapter is used.
Raw times are mapped through timemap.json; chapter starts are clamped to the master duration.
Outputs out/chapters.json (Podcasting 2.0, version 1.2.0), ID3 CHAP+CTOC in the MP3,
and work/transcript_edited.txt (edited-time transcript for show notes)."""
import argparse, json, subprocess
from pathlib import Path
from common import dump, load, load_cfg, log_step, r
from render import map_time


def mmss(t):
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True); a = ap.parse_args()
    ep = Path(a.ep); cfg = load_cfg(ep); slug = load(ep / "manifest.json")["slug"]
    tm = load(ep / "work/timemap.json")
    master = ep / "out" / f"{slug}_master.wav"
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(master)],
                               capture_output=True, text=True).stdout)
    src = ep / "chapters_raw.json"
    raw = load(src) if src.exists() else [{"raw_s": 0.0, "title": "オープニング"}]
    ch = sorted(({"startTime": r(min(map_time(tm, c["raw_s"]), dur), 3), "title": c["title"]} for c in raw), key=lambda c: c["startTime"])
    ch[0]["startTime"] = 0.0
    for p, q in zip(ch, ch[1:]):
        if q["startTime"] - p["startTime"] < cfg["chapters"]["min_gap_s"]:
            raise SystemExit(f"chapters '{p['title']}' and '{q['title']}' closer than chapters.min_gap_s")
    dump(ep / "out/chapters.json", {"version": "1.2.0", "chapters": ch})
    from mutagen.id3 import ID3, CHAP, CTOC, TIT2, CTOCFlags
    mp3 = ep / "out" / f"{slug}.mp3"
    tags = ID3()
    ends = [c["startTime"] for c in ch[1:]] + [dur]
    for i, (c, e) in enumerate(zip(ch, ends)):
        tags.add(CHAP(element_id=f"ch{i}", start_time=int(c["startTime"] * 1000), end_time=int(e * 1000),
                      sub_frames=[TIT2(text=[c["title"]])]))
    tags.add(CTOC(element_id="toc", flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED, child_element_ids=[f"ch{i}" for i in range(len(ch))],
                  sub_frames=[TIT2(text=["Chapters"])]))
    tags.save(str(mp3), v2_version=3, padding=lambda info: 0)
    words = load(ep / "work/words.json")
    lines = sorted((map_time(tm, g["start"]), s, g["text"]) for s, v in words.items() for g in v)
    (ep / "work/transcript_edited.txt").write_text("".join(f"{mmss(t)} {s}: {x}\n" for t, s, x in lines))
    log_step(ep, "chapters", {"n": len(ch)})
    print("chapters", [(mmss(c["startTime"]), c["title"]) for c in ch])


if __name__ == "__main__":
    main()
