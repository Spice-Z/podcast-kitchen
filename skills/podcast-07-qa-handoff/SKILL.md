---
name: podcast-07-qa-handoff
description: Use this as step 7 of a podcast edit: deterministic QA and handoff.
---
# Step 7: QA and handoff
`qa.py` (exit 1 on failure): LUFS/TP on the MP3 (the only deliverable), click and level-jump per join on the decoded MP3 (temp WAV deleted), leading/trailing silence ≤ `qa.edge_max_silence_s`, head/tail silence, long_pause count/removed/longest remaining gap, gate metric (non-speech bursts per track before/after gating, from logs/gate.json), edit counts. Hand off paths, `logs/qa.md`, cut summary by type, and the pending review list. Do not upload, publish or send.

## Handoff to the Publisher bot (rule)
When the package is final (QA PASS, no pending review), hand it to the separate **Publisher** bot. The editor never uploads or publishes.
1. `show_notes.md` must be in `out/`: after writing/updating `<ep>/show_notes.md`, run `pipeline/show_notes.py --ep <ep> --title "<title>"` (copies it to `out/show_notes.md` and prints the package; `qa.py` also copies it and lists anything missing).
2. Pass the Publisher:
   - paths: `out/<slug>.mp3`, `out/show_notes.md`, `out/chapters.json`
   - **title**: written by the editor from the episode content (main topics), not a placeholder
   - **publish time**: default the next Monday 07:00 JST, given with its Vancouver time (PT) equivalent converted with tzdata (`zoneinfo` America/Vancouver; never hardcode PST/PDT); use another time only if the owner says so
   - **artwork**: the show default
3. No personal info in the handoff beyond what is in the show notes.
