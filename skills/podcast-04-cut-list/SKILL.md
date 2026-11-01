---
name: podcast-04-cut-list
description: >-
  Use this as step 4 of a podcast edit: build an explicit, reviewable cut list
  (silences, false starts, crosstalk, mistakes) before touching the audio.
---
# Podcast step 4: cut list
Output: `work/cuts.json`, a list of `{start, end, type, reason, transcript_excerpt}` in raw-mix seconds. Every cut must be in this file; there are no hidden edits.

Rules, in priority order:
1. **Long silences:** run `silencedetect=n=-45dB:d=1.5` on `mix_raw.wav`. For each silence, shorten it to 0.6 s (cut the middle, keep 0.3 s on each side). Type `silence`.
2. **False starts:** a speaker repeats the same phrase within 3 s (from the transcript), or says 「すみません、もう一回」 or similar. Cut the first attempt from its start to the restart. Type `false_start`.
3. **Crosstalk blowups:** 2+ speakers overlap for more than 2 s and the words are unintelligible, or there is clipping/distortion. Type `crosstalk`.
4. **Obvious mistakes:** wrong facts that are corrected right after, or an explicit 「ここカットで」. Type `mistake`.

Never cut:
- anything that changes meaning,
- any joke or laugh, even to save time,
- content in the first 30 s or last 30 s, unless it is silence or pre-roll chatter before the intro.

If a cut isn't clearly one of these types, mark it `review` and don't apply it. Then list it for the user.
