---
name: podcast-06-show-notes
description: >-
  Use this as step 6 of a podcast edit: write Japanese show notes and mm:ss
  chapters timed against the edited audio.
---
# Podcast step 6: show notes and chapters
1. Re-transcribe `out/<slug>.mp3` with the same settings as step 3, or map the raw transcript through `timemap.json`. Chapters must use edited-file times, never raw times.
2. Write `out/<slug>_shownotes.md` in Japanese, in this fixed format:
   - `## 概要`: a 2–3 line summary
   - `## トピック`: bullets
   - `## 紹介したリンク`: every tool, site or product mentioned, with its official URL (search the web to confirm each one; leave out any you can't confirm and list them as unconfirmed)
   - `## チャプター`: `mm:ss タイトル`, starting at `00:00`, one at each topic change, at least 2 minutes apart
3. Spelling check: proper names of tools and companies must use their official spelling (e.g. GitHub, ChatGPT, OpenAI, AWS). Keep a log of the fixes in `logs/typos.md`.
