---
name: podcast-03-transcribe
description: Use this as step 3 of a podcast edit: VAD, ASR and kana forced alignment per speaker.
---
# Step 3: VAD, ASR, alignment
`vad.py` (Silero, `vad.*`; the only VAD) → `asr.py` (venv `env.venv_dfn_asr`; kotoba-whisper pinned revision, float32, temperature `[0.0]`, fallbacks logged) → `align_kana.py` (fugashi+unidic-lite POS, pyopenjtalk readings, MMS_FA; `align.*`). Low-score segments are marked `low` and their candidates go to review.
