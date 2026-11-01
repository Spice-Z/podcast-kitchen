---
name: podcast-07-qa-handoff
description: >-
  Use this as the final step of a podcast edit: QA the cut points, start/end and
  chapter times, then hand off the files with a cut summary.
---
# Podcast step 7: QA and handoff
The edit passes only if every check passes:
1. **Cut points:** for each applied cut, export a 3 s clip around the edited join (`work/qa/cut_###.wav`), re-transcribe it, and check that there's no clipped word (the first and last word must be complete) and no click (sample jump < 0.1 full scale).
2. **Start and end:** the first 30 s and last 30 s have no silence longer than 1 s and aren't cut off mid-word.
3. **Chapters:** for each chapter, transcribe 10 s from its timestamp in the edited MP3 and confirm it matches the chapter's topic. Fix the time if not.
4. **Loudness:** recheck -16 ±0.5 LUFS.
5. Write `logs/qa.md` with pass or fail for each check.

Handoff: send the MP3, the WAV master and `shownotes.md` in chat, with a short list of what was cut (count per type, plus every `review` item with its time). Never upload, publish or email.
