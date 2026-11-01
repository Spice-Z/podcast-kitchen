---
name: podcast-01-ingest
description: >-
  Use this as step 1 of a podcast edit: collect raw per-speaker tracks and any
  transcript into a fixed episode folder with a manifest.
---
# Podcast step 1: ingest
Input: downloaded per-speaker files (e.g. from Zencastr) and optional transcript.

1. Create `/workspace/podcast/<episode-slug>/` with subfolders `raw/ work/ out/ logs/`. Slug = `YYYY-MM-DD_<short-title>` in lowercase ASCII.
2. Move raw tracks to `raw/` and rename `track_<speaker>.<ext>` (speaker = lowercase ASCII name). Move the transcript to `raw/transcript.<ext>` if there is one.
3. For each track run `ffprobe -v error -show_entries format=duration:stream=sample_rate,channels,codec_name -of json` and save the results to `logs/probe.json`.
4. Convert each track to `work/<speaker>.wav` with `ffmpeg -i IN -ac 1 -ar 48000 -c:a pcm_s24le`.
5. Write `manifest.json` with episode slug, title, recorded date, speakers, file paths, durations, and whether a transcript exists.

Stop condition: when `manifest.json` exists and every track has a `work/*.wav`. If any track is missing or its duration differs from the longest by more than 5 s, stop and report it. Never delete anything at the source.
