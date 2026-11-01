---
name: podcast-05-render
description: Use this as step 5 of a podcast edit: apply edits.json and normalize loudness.
---
# Step 5: render and loudness
`render.py` applies only approved edits (snap ±`render.snap_window_ms`, `render.crossfade_ms` equal-power on all tracks, room tone, `render.duck_db`), writes `work/mix.wav` (dual-mono) and `work/timemap.json`. `loudness.py`: ffmpeg loudnorm two-pass linear to `loudness.target_lufs` / `loudness.max_true_peak_dbtp`, fails if not linear; writes the WAV master and 192k MP3.
