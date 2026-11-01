"""Import an Audacity label file edited by a human: first word OK/NG/cut/duck/mute/keep, then the key.
'OK <key> ...' approves the current action; 'NG <key>' sets keep. Unknown lines are reported and ignored."""
import argparse, sys
from pathlib import Path
from common import dump, load


def apply(lines, labels):
    changed, bad = 0, []
    for ln in lines:
        parts = ln.rstrip("\n").split("\t")
        if len(parts) < 3:
            continue
        w = parts[2].split()
        if len(w) < 2 or w[1] not in labels:
            bad.append(ln.strip()); continue
        d, k = w[0], w[1]
        L = labels[k]
        if d == "OK" and L["action"] != "review":
            L["approved"] = True
        elif d == "NG":
            L.update(action="keep", approved=True)
        elif d in ("cut", "duck", "mute", "keep"):
            L.update(action=d, approved=True)
        else:
            continue
        L["labeler"] = "human"; changed += 1
    return changed, bad


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True); ap.add_argument("labels_txt"); a = ap.parse_args()
    ep = Path(a.ep); labels = load(ep / "labels.json")
    n, bad = apply(Path(a.labels_txt).read_text().splitlines(), labels)
    dump(ep / "labels.json", labels)
    print("updated", n, "unparsed", len(bad))
    for b in bad: print("  ?", b, file=sys.stderr)


if __name__ == "__main__":
    main()
