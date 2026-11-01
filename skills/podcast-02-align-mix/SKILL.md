---
name: podcast-02-align-mix
description: Use this as step 2 of a podcast edit: clean and level each track.
---
# Step 2: clean and level
`clean_dfn.py` (venv `env.venv_dfn_asr`, `clean.dfn_atten_lim_db`) → `clean_dynamics.py` (HPF, de-ess, compressor, limiter: `clean.*`) → `level.py` (`level.*`). No afftdn. The mix is made by render, not here.
