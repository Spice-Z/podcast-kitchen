---
name: podcast-06-show-notes
description: Use this as step 6 of a podcast edit: chapters (no re-ASR) and show notes.
---
# Step 6: chapters and show notes
Write `<ep>/chapters_raw.json` (`[{raw_s, title}]`) from the raw transcript, then `chapters.py` maps through `timemap.json` (which already includes the jingle shift — never add it by hand), writes `out/chapters.json` (Podcasting 2.0) and ID3 CHAP/CTOC, plus `work/transcript_edited.txt`. Show notes (Japanese): 2–3 line summary, topic bullets, links, mm:ss chapters. Link lookup is optional; mark every unchecked link 未確認.
