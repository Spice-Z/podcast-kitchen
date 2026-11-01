---
name: podcast-01-ingest
description: Use this as step 1 of a podcast edit: copy and decode per-speaker tracks and the Zencastr transcript.
---
# Step 1: ingest
Always export BOTH Zencastr transcript files with the tracks: the timed TSV/CSV (Timestamp, Speaker, Transcript; the primary text source) and the TXT (for show notes). Full kotoba ASR runs only when Zencastr has no transcript.

Run `pipeline/ingest.py --ep <ep> --track spk=path … --transcript x.csv --transcript x.txt --speaker "Zencastr Name=spk" …` (venv `env.venv_main`). It copies (never moves) sources to `raw/` (CSV → `raw/transcript.csv`), stores the speaker map only in the episode `manifest.json` (never in the repo), checks ffmpeg/LAME versions, applies LAME gapless delay/padding, decodes with soxr per `ingest.*`, logs start offsets to `logs/probe.json`, and fails past `ingest.max_start_offset_s` / `ingest.max_length_diff_s`. Then `pipeline/sync.py` (longest track as reference, `sync.*`; any applied shift is recorded as `applied_offset_s` and used to place transcript times).
