"""Export unapproved/review edits as an Audacity label track (work/review_labels.txt).
Label text: '<key> <type>/<action> <track> | <excerpt>'. Edit the first word in Audacity to
OK (approve as is), NG (keep, i.e. do not edit), or one of cut/duck/mute/keep, then review_import.py."""
import argparse
from pathlib import Path
from common import load


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True); ap.add_argument("--all", action="store_true"); a = ap.parse_args()
    ep = Path(a.ep)
    rows = [e for e in load(ep / "work/edits.json") if a.all or not e["approved"] and e["action"] != "keep" or e["action"] == "review"]
    out = ep / "work/review_labels.txt"
    out.write_text("".join(f"{e['start']:.3f}\t{e['end']:.3f}\t{e['key']} {e['type']}/{e['action']} {e['track']} | {e['excerpt'][:40]}\n" for e in rows))
    print(out, len(rows))


if __name__ == "__main__":
    main()
