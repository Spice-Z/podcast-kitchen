---
name: podcast-03-transcribe
description: Use this as step 3 of a podcast edit: per-speaker Japanese transcription with kotoba-whisper float32 plus MMS forced alignment for character-level times.
---
# Podcast step 3: transcription and alignment
1. Run Silero VAD on each speaker track and save the speech segments.
2. Transcribe each speaker track with kotoba-whisper-v2.0 in float32, temperature 0, beam 5 (int8 is banned: the output breaks). Don't use Whisper's own word timestamps; they crash.
3. Get character-level times with torchaudio MMS_FA forced alignment plus uroman.
4. If a Zencastr transcript exists, use it to check the text.
5. Write `work/transcript_raw.json` (speaker, start, end, text, chars[]) and `transcript_raw.txt`.
