"""Step 4b: persistent labels and the single edit list.

labels.json (episode root, survives reruns) is keyed by candidate key = hash(type, track, times, excerpt, context).
Labels are never regenerated: `seed` only adds missing keys with the rule default.
  seed                       add rule labels for new candidates
  set KEY ACTION [--approve] [--by agent|human] [--note ...]
  approve --types a,b        bulk-approve current actions (test harness / explicit user instruction only)
  build                      write work/edits.json (fails if any candidate lacks a label)
  status                     counts
edits.json entry: {id, key, type, track, start, end, action, approved, labeler, reason, excerpt, confidence, note}
manual_edits.json (optional, episode root): [{start, end, track, action, approved, note}] for edits no rule can find
(e.g. a retake the ASR merged away). They are appended as type "manual" with key m-<start>-<end>.
Render applies an entry only if approved is true and action in {cut, duck, mute}."""
import argparse, sys
from pathlib import Path
from common import dump, load, load_cfg

ACTIONS = ("cut", "duck", "mute", "keep", "review")


def seed(cands, labels, cfg):
    auto = set(cfg["labels"]["auto_approve_types"]); n = 0
    for c in cands:
        if c["key"] in labels:
            continue
        a = c["default_action"]
        labels[c["key"]] = {"action": a, "labeler": "rule", "approved": a in ("cut", "duck", "mute", "keep") and c["type"] in auto, "note": ""}
        n += 1
    return n


def build(cands, labels):
    missing = [c["key"] for c in cands if c["key"] not in labels]
    if missing:
        raise SystemExit(f"unlabeled candidates: {len(missing)} (e.g. {missing[:3]}); run label_store.py seed")
    out = []
    for i, c in enumerate(cands):
        L = labels[c["key"]]
        if L["action"] not in ACTIONS:
            raise SystemExit(f"bad action {L['action']} for {c['key']}")
        out.append({"id": f"e{i:04d}", "key": c["key"], "type": c["type"], "track": c["track"], "start": c["start"], "end": c["end"],
                    "action": L["action"], "approved": bool(L["approved"]) and L["action"] != "review", "labeler": L["labeler"],
                    "reason": c["reason"], "excerpt": c["excerpt"], "confidence": c["confidence"], "note": L.get("note", "")})
    return out


def manual(ep):
    p = ep / "manual_edits.json"
    out = []
    for i, m in enumerate(load(p) if p.exists() else []):
        if m["action"] not in ACTIONS or not m["end"] > m["start"]:
            raise SystemExit(f"bad manual edit {m}")
        out.append({"id": f"m{i:04d}", "key": f"m-{m['start']:.3f}-{m['end']:.3f}", "type": "manual", "track": m.get("track", "all"),
                    "start": m["start"], "end": m["end"], "action": m["action"], "approved": bool(m.get("approved")) and m["action"] != "review",
                    "labeler": m.get("by", "agent"), "reason": "manual edit", "excerpt": m.get("excerpt", ""), "confidence": 1.0, "note": m.get("note", "")})
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("seed"); sp.add_parser("build"); sp.add_parser("status")
    s = sp.add_parser("set"); s.add_argument("key"); s.add_argument("action", choices=ACTIONS)
    s.add_argument("--approve", action="store_true"); s.add_argument("--by", default="agent"); s.add_argument("--note", default="")
    b = sp.add_parser("approve"); b.add_argument("--types", required=True)
    a = ap.parse_args()
    ep = Path(a.ep); cfg = load_cfg(ep)
    cands = load(ep / "work/candidates.json")
    lp = ep / "labels.json"
    labels = load(lp) if lp.exists() else {}
    if a.cmd == "seed":
        n = seed(cands, labels, cfg); dump(lp, labels); print("seeded", n, "total", len(labels))
    elif a.cmd == "set":
        if a.key not in labels:
            sys.exit("unknown key")
        labels[a.key] = {"action": a.action, "labeler": a.by, "approved": a.approve, "note": a.note}; dump(lp, labels)
    elif a.cmd == "approve":
        types = set(a.types.split(",")); n = 0
        for c in cands:
            L = labels.get(c["key"])
            if L and c["type"] in types and L["action"] != "review" and not L["approved"]:
                L["approved"] = True; n += 1
        dump(lp, labels); print("approved", n)
    elif a.cmd == "build":
        e = build(cands, labels) + manual(ep); dump(ep / "work/edits.json", e)
        print("edits", len(e), "applied", sum(1 for x in e if x["approved"] and x["action"] in ("cut", "duck", "mute")))
    else:
        from collections import Counter
        print(Counter((labels[c["key"]]["action"], labels[c["key"]]["approved"]) for c in cands if c["key"] in labels))


if __name__ == "__main__":
    main()
