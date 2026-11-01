---
name: podcast-05-render
description: Use this as step 5 of a podcast edit: apply the approved edit list to all tracks in sync, mix, and render -16 LUFS WAV master and MP3 192k.
---
# Podcast step 5: render
1. Apply the `cut` and `duck` entries in `edits.json`; skip `review` items that haven't been approved. Cuts apply to every track at once so they stay in sync.
2. Snap each cut point to the quiet spot or zero crossing nearest it (within 30 ms).
3. Crossfades are equal-power: 10 ms within one speaker, 30 ms where the speaker changes. Fill gaps with that track's room tone.
4. Lower breaths by 6 dB instead of cutting them.
5. Mix, then bring loudness to -16 LUFS and true peak to -1.5 dBTP with pyloudnorm, then a two-pass ffmpeg loudnorm. Output a 48 kHz / 24-bit WAV master and a 192k stereo MP3.
6. Write `work/timemap.json`.
