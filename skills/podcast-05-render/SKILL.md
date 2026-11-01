---
name: podcast-05-render
description: >-
  Use this as step 5 of a podcast edit: apply the cut list and render the -16
  LUFS WAV master and stereo MP3 192k.
---
# Podcast step 5: render
1. Apply `work/cuts.json`, skipping cuts of type `review`. Join the kept segments with a 10 ms crossfade (`acrossfade=d=0.01`) at every cut. Write `work/edited.wav`.
2. Save a time map `work/timemap.json` (raw time to edited time) so later steps can convert times.
3. Loudness: two-pass `loudnorm=I=-16:TP=-1.5:LRA=11` using the measured values from pass 1, then write `out/<slug>_master.wav` (48 kHz, 24-bit, stereo).
4. MP3: `ffmpeg -i master.wav -codec:a libmp3lame -b:a 192k -ac 2 -ar 44100 out/<slug>.mp3`.
5. Verify with `ebur128`: integrated loudness must be -16 ±0.5 LUFS and true peak ≤ -1.0 dBTP. If either fails, stop and report.
