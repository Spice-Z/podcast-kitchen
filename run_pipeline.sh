#!/usr/bin/env bash
# Usage: run_pipeline.sh <episode_dir> prep   --track host=a.mp3 --track guest_a=b.mp3 ... [--transcript t.txt]
#        run_pipeline.sh <episode_dir> finish   (after review: labels.json complete)
# Stops on the first failing step. Venvs come from config.yaml env.* (override with VENV_DFN / VENV_MAIN).
set -euo pipefail
EP=$1; PHASE=$2; shift 2
HERE=$(cd "$(dirname "$0")" && pwd); P=$HERE/pipeline
cfg() { python3 -c "import yaml,sys;print(yaml.safe_load(open('$HERE/config.yaml'))['env'][sys.argv[1]])" "$1" 2>/dev/null \
        || "${VENV_MAIN:-/workspace/podcast/smoke/.venv2}/bin/python" -c "import yaml,sys;print(yaml.safe_load(open('$HERE/config.yaml'))['env'][sys.argv[1]])" "$1"; }
DFN=${VENV_DFN:-$(cfg venv_dfn_asr)}/bin/python
MAIN=${VENV_MAIN:-$(cfg venv_main)}/bin/python
step() { echo "== $1"; shift; "$@"; }
case $PHASE in
  prep)
    step ingest      $MAIN $P/ingest.py --ep "$EP" "$@"
    step sync        $MAIN $P/sync.py --ep "$EP"
    step clean_dfn   $DFN  $P/clean_dfn.py --ep "$EP"
    step clean_dyn   $MAIN $P/clean_dynamics.py --ep "$EP"
    step level       $MAIN $P/level.py --ep "$EP"
    step vad         $MAIN $P/vad.py --ep "$EP"
    step asr         $DFN  $P/asr.py --ep "$EP"
    step align_kana  $MAIN $P/align_kana.py --ep "$EP"
    step candidates  $MAIN $P/candidates.py --ep "$EP"
    step seed        $MAIN $P/label_store.py --ep "$EP" seed
    step export      $MAIN $P/review_export.py --ep "$EP"
    $MAIN $P/label_store.py --ep "$EP" status ;;
  finish)
    step build       $MAIN $P/label_store.py --ep "$EP" build
    step render      $MAIN $P/render.py --ep "$EP"
    step loudness    $MAIN $P/loudness.py --ep "$EP"
    step chapters    $MAIN $P/chapters.py --ep "$EP"
    step qa          $MAIN $P/qa.py --ep "$EP" ;;
  *) echo "phase must be prep|finish" >&2; exit 2 ;;
esac
