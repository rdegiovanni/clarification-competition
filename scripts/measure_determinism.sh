#!/usr/bin/env bash
# Determinism check on the flaky smoke tasks (results/flaky_sets/): laaser_pinpoint_smt_3.py with
# its defaults vs. with voting, N runs each. Compare how many tasks keep the same outcome across
# the runs of each variant (results/runs/*_det-*). Dev tooling, not part of the submission.
#
# Usage: scripts/measure_determinism.sh [runs, default 3]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."
export PYTHONINTMAXSTRDIGITS=0

RUNS="${1:-3}"
COMMON=(--clarify-py clarify/algorithms/laaser_pinpoint_smt_3.py --language-model openai/gpt-4.1-mini)
VOTE="--decision_votes 5 --question_choice consensus --candidates 5"
mkdir -p results/flaky_sets/logs

for r in $(seq 1 "$RUNS"); do
  for v in base vote; do
    extra=()
    [[ $v == vote ]] && extra=(--extra-gen-args "$VOTE")
    for c in mbpp humaneval; do
      scripts/evaluate.sh "${COMMON[@]}" ${extra[@]+"${extra[@]}"} \
        --dataset-path "results/flaky_sets/${c}_flaky.jsonl" --label "det-$v-r$r-$c" \
        > "results/flaky_sets/logs/det-$v-r$r-$c.log" 2>&1 &
      sleep 3
    done
    wait
    echo "done $v r$r"
  done
done
