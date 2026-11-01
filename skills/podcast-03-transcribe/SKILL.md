---
name: podcast-03-transcribe
description: >-
  Use this as step 3 of a podcast edit: produce a word-timestamped Japanese
  transcript of the raw mix to find cut candidates.
---
# Podcast step 3: transcribe (raw)
1. If `raw/transcript.*` exists, convert it to `work/transcript_raw.json` (segments with start, end, speaker, text).
2. Otherwise run faster-whisper: model `large-v3`, `language=ja`, `word_timestamps=True`, `vad_filter=True`, beam_size 5. Run it per speaker on `work/<speaker>_clean.wav` so speaker labels come for free, then merge the segments sorted by start time.
3. Save to `work/transcript_raw.json` and a readable `work/transcript_raw.txt` (`[mm:ss] speaker: text`).

The settings are fixed so reruns give the same output.
