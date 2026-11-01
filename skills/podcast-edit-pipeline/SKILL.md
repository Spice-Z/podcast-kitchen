---
name: podcast-edit-pipeline
description: Use this when asked to edit a podcast episode end to end. Runs the repo scripts in order; all parameters live in config.yaml.
---
# Podcast edit pipeline
0. Get the Zencastr transcript exports (CSV + TXT) with the tracks. They are the primary text (`transcript.source: zencastr`); full ASR is only the fallback when no CSV exists.
1. Run every long step in the background (`nohup … > log 2>&1 &`) and poll; steps are resumable (rerun skips stages whose outputs exist; `RESUME=0` forces).
   `./run_pipeline.sh <ep> prep --track host=… --track guest_a=… --transcript z.csv --transcript z.txt --speaker "Name=host" …` (steps 01–04; stops on first failure).
2. Label review items (@podcast-04-cut-list), then `./run_pipeline.sh <ep> finish` (05–07).
Do not change parameters in prose; edit `config.yaml` and record why in `<ep>/logs/notes.md`. Episode folders live outside the repo. Never upload, post or send.
