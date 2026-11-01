---
name: podcast-01-ingest
description: Use this as step 1 of a podcast edit: copy and decode per-speaker tracks.
---
# Step 1: ingest
Run `pipeline/ingest.py --ep <ep> --track spk=path …` (venv `env.venv_main`). It copies (never moves) sources to `raw/`, checks ffmpeg/LAME versions, applies LAME gapless delay/padding, decodes with soxr per `ingest.*`, logs start offsets to `logs/probe.json`, and fails past `ingest.max_start_offset_s` / `ingest.max_length_diff_s`. Then `pipeline/sync.py` (longest track as reference, `sync.*`).
