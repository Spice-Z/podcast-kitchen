---
name: podcast-04-cut-list
description: Use this as step 4 of a podcast edit: build and label the explicit edit list (long_pause, filler, backchannel, overlap_yield, false_start, crosstalk, mistake).
---
# Step 4: edit list
1. `candidates.py` → `work/candidates.json` (rules in playbook §3, thresholds `candidates.*`, word lists `text.*`).
2. `label_store.py seed` (rule labels; auto-approve only `labels.auto_approve_types`; existing labels are reused, keyed by hash(candidate+context)).
3. For each non-auto candidate read `context`, then `label_store.py set <key> <cut|duck|mute|keep|review> [--approve] --by agent --note …`. Anything touching meaning, jokes/laughs, or a pause before a laugh stays `review` for the user (`review_export.py` → Audacity → `review_import.py`).
4. `label_store.py build` writes `work/edits.json`; it fails on unlabeled candidates.
Types: `long_pause` (union-VAD gaps > 1.2 s within / 1.5 s between speakers → 0.7 s, review if laugh within 2 s), `filler`, `backchannel` (-20 dB duck on own track), `overlap_yield` (mute only the yielder), `false_start`, `crosstalk`, `mistake`. Never cut meaning, jokes, laughs, or head/tail content.
