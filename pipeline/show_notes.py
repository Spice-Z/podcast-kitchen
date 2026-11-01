"""Step 6b/7: publish package for the Publisher bot. Copies <ep>/show_notes.md to out/show_notes.md and prints the
handoff block: out/<slug>.mp3, out/show_notes.md, out/chapters.json, title (written by the editor from the episode
content), publish time (default next Monday 07:00 JST, with the Vancouver time (PT) equivalent from tzdata) and artwork = show default.
The editor never uploads or publishes; this only writes inside the episode folder."""
import argparse, json, shutil
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from common import load, load_cfg

JST, PT = ZoneInfo("Asia/Tokyo"), ZoneInfo("America/Vancouver")  # local tzdata decides the offset


def next_publish(now=None, weekday=0, hour=7):
    """Next <weekday> <hour>:00 JST strictly after `now` (aware datetime; default: current time)."""
    now = (now or datetime.now(JST)).astimezone(JST)
    t = now.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=(weekday - now.weekday()) % 7)
    return t if t > now else t + timedelta(days=7)


def mmss(t):
    return f"{int(t // 60)}:{t % 60:05.2f}"


def ad_point(ep, cfg_pre=0.4):
    """Ad insertion point = start of the pre-jingle silence on the final timeline (jingle_start_s - pre_silence_s;
    jingle runs after render and only ending_bgm/loudness follow, which never shift earlier audio). None if no jingle."""
    p = ep / "logs/jingle.json"
    if not p.exists():
        return None
    j = load(p)
    if not j.get("applied") or j.get("jingle_start_s") is None:
        return None
    try:
        pre = load_cfg(ep)["jingle"]["pre_silence_s"]
    except Exception:
        pre = cfg_pre
    from decimal import Decimal, ROUND_HALF_UP
    t = float(Decimal(str(round(j["jingle_start_s"] - pre, 3))).quantize(Decimal("0.01"), ROUND_HALF_UP))
    return {"seconds": t, "mmss": mmss(t)}


def copy_notes(ep):
    src, dst = ep / "show_notes.md", ep / "out" / "show_notes.md"
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(src, dst)
    return dst if dst.exists() else None


def package(ep, title=None, now=None):
    slug = load(ep / "manifest.json")["slug"]
    notes = copy_notes(ep)
    t = next_publish(now)
    files = {"audio": ep / "out" / f"{slug}.mp3", "show_notes": ep / "out" / "show_notes.md", "chapters": ep / "out" / "chapters.json"}
    ad = ad_point(ep)
    missing = [k for k, v in files.items() if not v.exists()] + ([] if ad else ["ad_insertion_point (no applied jingle)"])
    return {"files": {k: str(v) for k, v in files.items()}, "missing": missing, "ad_insertion_point": ad,
            "title": title or "(editor: write the title from the episode content)",
            "publish_at_jst": t.strftime("%Y-%m-%d %H:%M JST (%a)"), "publish_at_pt": t.astimezone(PT).strftime("%Y-%m-%d %H:%M") + " Vancouver time (PT) " + t.astimezone(PT).strftime("(%a)"),
            "artwork": "show default", "notes_copied": notes is not None}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True); ap.add_argument("--title")
    a = ap.parse_args()
    print(json.dumps(package(Path(a.ep), a.title), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
