---
name: podcast-edit-pipeline
description: >-
  Use this when asked to edit a podcast episode end to end: runs steps 01–07 in
  order with fixed settings.
---
# Podcast edit pipeline
Run these in order. Each step reads the previous step's files and writes its own, so a failed step can be rerun alone.
1. @podcast-01-ingest
2. @podcast-02-align-mix
3. @podcast-03-transcribe
4. @podcast-04-cut-list
5. @podcast-05-render
6. @podcast-06-show-notes
7. @podcast-07-qa-handoff

All settings are fixed in the step skills. Any deviation must be recorded in `logs/notes.md` with a reason, and reported at handoff.
