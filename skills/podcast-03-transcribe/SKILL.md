---
name: podcast-03-transcribe
description: Use this as step 3 of a podcast edit: VAD, transcript (Zencastr TSV first, ASR fallback) and kana forced alignment per speaker.
---
# Step 3: VAD, transcript, alignment
1. `vad.py` (Silero, `vad.*`; the only VAD).
2. Text. If `raw/transcript.csv` exists (Zencastr TSV: Timestamp, Speaker, Transcript; pass it with `--transcript x.csv` and map names with `--speaker "Name=track"` at ingest; the map stays in the episode manifest, never in the repo): `zencastr_transcript.py` → `work/asr.json` (one segment per utterance, start snapped to the speaker's VAD onset, end clipped by the next same-speaker utterance; `transcript.*`). Uncovered VAD islands go to `logs/transcript_coverage.json`. Only if `asr.fallback: gaps` does `asr.py --gaps` (kotoba-whisper) transcribe those spans and merge them. Without a CSV, `asr.py` runs on the whole episode (slow: ~1.5x real time, ~5.6 GB RAM; never run two at once).
3. `align_kana.py` (fugashi+unidic-lite POS, pyopenjtalk readings, MMS_FA; `align.*`) aligns each utterance on its speaker's track. Low-score segments are marked `low` and their candidates go to review.
Filler/backchannel detection keeps its acoustic path (islands with no text) as well.
