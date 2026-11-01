---
name: podcast-04-cut-list
description: Use this as step 4 of a podcast edit: build an explicit, reviewable edit list (silences, fillers, excess backchannels, overlap/yield, false starts, crosstalk, mistakes) before touching audio.
---
# Podcast step 4: edit list
Output: `work/edits.json`, a list of `{id, start, end, track (or 'all'), type, action (cut|duck|keep), reason, excerpt, confidence}` in raw seconds. No edit happens outside this file.

Three stages, in this order:
1. **Rule-based candidates**, using per-speaker Silero VAD and character-aligned transcripts.
2. **LLM labeling:** the agent reads the context around each candidate and labels it cut, keep, or review. Save the labels and reuse them; never regenerate them.
3. **Human approval:** `review` items wait for the user.

## Required edit types
- `silence`: a gap of 1.5 s or more when nobody is speaking. Shorten it to 0.6 s and fill with room tone.
- `filler` (required): stand-alone fillers such as えー, あー, んー, えっと, あのー, まあ, なんか, そのー. Cut them when they are in a run, or when they sit in a pause and removing them doesn't change the rhythm. Keep the ones that carry emphasis or feeling.
- `backchannel` (required): うん, へー, なるほど, そうそう, はい, and similar, on a listener's track. Keep at most 1 every 10 s per listener. Keep the ones that react to a joke or carry agreement. Take out the excess with `duck` on that track only (-30 dB, 20 ms fades), not by cutting the timeline.
- `overlap_yield` (required): two or more speakers start at the same time (within 0.5 s), then stop and give way (「あ、どうぞ」「ごめん」 and the like). Cut from the first collision to the restart of the speaker who keeps talking, on all tracks.
- `false_start`: the same phrase repeated within 3 s, or saying something again. Cut the first attempt.
- `crosstalk`: overlap of 2 s or more that you can't make out, or clipping.
- `mistake`: a misstatement corrected right away, or 「ここカットで」.

## Never cut
Anything that changes meaning; jokes, laughs, or reactions to a joke; real content in the first or last 30 s. When unsure, mark it `review`.
