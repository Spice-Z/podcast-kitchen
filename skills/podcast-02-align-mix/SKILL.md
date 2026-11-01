---
name: podcast-02-align-mix
description: >-
  Use this as step 2 of a podcast edit: line up the per-speaker tracks and clean
  each one (noise reduction, level) before mixing.
---
# Podcast step 2: align and clean tracks
Input: `work/<speaker>.wav` from step 1.

1. Alignment: Zencastr tracks start at the same time, so the default offset is 0. Check by cross-correlating the first 120 s of each track against the longest track (numpy/scipy, 8 kHz downsample). Apply the offset only if the correlation peak is clear and |offset| > 20 ms; otherwise keep 0. Save the offsets to `logs/align.json`.
2. Per-track cleanup, applied in this fixed order:
   `highpass=f=80, afftdn=nr=12:nf=-50, acompressor=threshold=-20dB:ratio=3:attack=5:release=100`
3. Write `work/<speaker>_clean.wav` (48 kHz, 24-bit, mono).
4. Mix: pan each speaker to center, `amix=inputs=N:normalize=0`, and write `work/mix_raw.wav` (stereo, 48 kHz).
5. Save the exact ffmpeg commands to `logs/commands.sh`.

Never change the filter values ad hoc. If a track needs something different, record the reason in `logs/notes.md` first.
