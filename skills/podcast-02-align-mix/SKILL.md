---
name: podcast-02-align-mix
description: Use this as step 2 of a podcast edit: check sync and clean each speaker track (DeepFilterNet3 denoise, pedalboard EQ/dynamics) with pinned settings.
---
# Podcast step 2: sync and per-track cleanup
1. **Sync:** cross-correlate the start and end of each track against the reference track. If drift is over 20 ms, correct it by resampling. Save `logs/align.json`.
2. **Denoise:** run DeepFilterNet3 in its own Python 3.11 environment (torch 2.0.1 and torchaudio 2.0.2), with attenuation capped at 18 dB so laughs and breaths aren't damaged. Write `work/<spk>_dn.wav`.
3. **EQ and dynamics** with pedalboard, using fixed settings from `config.yaml`: high-pass at 80 Hz, de-esser, compressor (threshold -20 dB, ratio 3), limiter.
4. **Leveler:** match each speaker to -20 LUFS.
5. Record package versions and model hashes in `logs/env.json`.
