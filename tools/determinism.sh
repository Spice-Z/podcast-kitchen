#!/usr/bin/env bash
# Run the full pipeline twice into fresh dirs and compare hashes of every output/work artifact.
# Usage: tools/determinism.sh <outroot> <labels_approve_types|-> --track spk=path ... [--transcript t]
set -euo pipefail
ROOT=$1; APPROVE=$2; shift 2; HERE=$(cd "$(dirname "$0")/.." && pwd)
MAIN=${VENV_MAIN:-/workspace/podcast/smoke/.venv2}/bin/python
for r in a b; do
  rm -rf "$ROOT/$r"; mkdir -p "$ROOT/$r"
  "$HERE/run_pipeline.sh" "$ROOT/$r" prep "$@" > "$ROOT/$r.prep.log" 2>&1
  [ "$APPROVE" != "-" ] && $MAIN "$HERE/pipeline/label_store.py" --ep "$ROOT/$r" approve --types "$APPROVE" >> "$ROOT/$r.prep.log"
  "$HERE/run_pipeline.sh" "$ROOT/$r" finish > "$ROOT/$r.finish.log" 2>&1 || echo "finish exit $? (see $ROOT/$r.finish.log)"
  (cd "$ROOT/$r" && find out work labels.json -type f ! -name '*.txt.tmp' | sort | xargs sha256sum) > "$ROOT/$r.sha"
done
if diff <(cut -c1-64,66- "$ROOT/a.sha") <(cut -c1-64,66- "$ROOT/b.sha") > "$ROOT/diff.txt"; then
  echo "DETERMINISTIC: $(wc -l < "$ROOT/a.sha") files identical"
else
  echo "NONDETERMINISTIC:"; cat "$ROOT/diff.txt"; exit 1
fi
