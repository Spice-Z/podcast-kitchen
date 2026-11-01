---
name: podcast-edit-pipeline
description: Use this when asked to edit a podcast episode end to end. Runs the repo scripts in order; all parameters live in config.yaml.
---
# Podcast edit pipeline
1. `./run_pipeline.sh <ep> prep --track host=… --track guest_a=… [--transcript …]` (steps 01–04; stops on first failure).
2. Label review items (@podcast-04-cut-list), then `./run_pipeline.sh <ep> finish` (05–07).
Do not change parameters in prose; edit `config.yaml` and record why in `<ep>/logs/notes.md`. Episode folders live outside the repo. Never upload, post or send.
