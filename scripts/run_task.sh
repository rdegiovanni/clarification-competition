#!/usr/bin/env bash
# Runs ONE specific MBPP/HumanEval task through generate_responses.py + evaluate_responses.py,
# for quick debugging of a single task_id without building a full smoke/val dataset.
#
# Usage:
#   scripts/run_task.sh --clarify-py clarify/algorithms/laaser_pinpoint.py --mbpp 229
#   scripts/run_task.sh --clarify-py clarify/algorithms/laaser_pinpoint.py --humaneval 15
#
# Pass exactly one of --mbpp N or --humaneval N. The task is pulled from the unperturbed
# *_original.jsonl file by task_id; generate_responses.py still attaches real hidden
# requirements from data/clarifications.jsonl automatically if that (task_id, prompt) has any,
# exactly as it does for any other dataset file.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

CLARIFY_PY=""
MBPP=""
HUMANEVAL=""
LANGUAGE_MODEL="${LANGUAGE_MODEL:-openai/gpt-4.1-mini}"
TEMPERATURE="0.7"
OUT_DIR=""
SKIP_EVALUATE=0

usage() {
  cat <<'EOF'
Usage: scripts/run_task.sh --clarify-py PATH (--mbpp N | --humaneval N) [options]

  --clarify-py PATH       Algorithm file to run (required)
  --mbpp N                Run Mbpp/N (mutually exclusive with --humaneval)
  --humaneval N           Run HumanEval/N (mutually exclusive with --mbpp)
  --language-model MODEL  LiteLLM model string (default: $LANGUAGE_MODEL env var, or openai/gpt-4.1-mini)
  --temperature T         Sampling temperature forwarded to generate_responses.py (default: 0.7)
  --skip-evaluate         Only generate the response, skip the Docker-sandboxed evaluation
  -h, --help              Show this help

Output: results/single_task/<Mbpp_N or HumanEval_N>/{task.jsonl,generate.jsonl,results.jsonl},
plus a printed summary (asked question/answer, final code, PASS/FAIL and test output).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --clarify-py) CLARIFY_PY="$2"; shift 2 ;;
    --mbpp) MBPP="$2"; shift 2 ;;
    --humaneval) HUMANEVAL="$2"; shift 2 ;;
    --language-model) LANGUAGE_MODEL="$2"; shift 2 ;;
    --temperature) TEMPERATURE="$2"; shift 2 ;;
    --skip-evaluate) SKIP_EVALUATE=1; shift 1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$CLARIFY_PY" ]]; then
  echo "Error: --clarify-py is required" >&2; usage; exit 1
fi
if [[ -n "$MBPP" && -n "$HUMANEVAL" ]] || [[ -z "$MBPP" && -z "$HUMANEVAL" ]]; then
  echo "Error: pass exactly one of --mbpp N or --humaneval N" >&2; usage; exit 1
fi

if [[ -n "$MBPP" ]]; then
  CLASS_NAME="Mbpp"; NUMBER="$MBPP"; ORIGINAL_FILE="data/mbpp/mbpp_original.jsonl"
else
  CLASS_NAME="HumanEval"; NUMBER="$HUMANEVAL"; ORIGINAL_FILE="data/humaneval/humaneval_original.jsonl"
fi
TASK_ID="${CLASS_NAME}/${NUMBER}"
SAFE_ID="${CLASS_NAME}_${NUMBER}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

OUT_DIR="results/single_task/${SAFE_ID}"
mkdir -p "$OUT_DIR"
DATASET_PATH="$OUT_DIR/task.jsonl"

uv run python3 -c "
import json, sys
task_id = '$TASK_ID'
with open('$ORIGINAL_FILE') as f:
    for line in f:
        row = json.loads(line)
        if row['task_id'] == task_id:
            with open('$DATASET_PATH', 'w') as out:
                out.write(json.dumps(row) + chr(10))
            sys.exit(0)
sys.exit(f'{task_id} not found in $ORIGINAL_FILE')
"

echo "== generating ($TASK_ID, $(basename "$CLARIFY_PY" .py), $LANGUAGE_MODEL) =="
GEN_PATH="$OUT_DIR/generate.jsonl"
PYTHONINTMAXSTRDIGITS=0 uv run python generate_responses.py "$CLARIFY_PY" \
  --dataset_path "$DATASET_PATH" --output_path "$GEN_PATH" \
  --language_model "$LANGUAGE_MODEL" --temperature "$TEMPERATURE"

if [[ "$SKIP_EVALUATE" -eq 1 ]]; then
  echo "== skipped evaluation (--skip-evaluate); see $GEN_PATH =="
  exit 0
fi

echo "== evaluating (Docker sandbox) =="
RESULTS_PATH="$OUT_DIR/results.jsonl"
PYTHONINTMAXSTRDIGITS=0 uv run python evaluate_responses.py \
  --benchmark_path "$DATASET_PATH" --generation_path "$GEN_PATH" \
  --output_path "$RESULTS_PATH" --force_rerun

uv run python3 -c "
import json
with open('$RESULTS_PATH') as f:
    r = json.loads(f.readline())
print()
print('===', r['task_id'], '->', 'PASS' if r['success'] else 'FAIL', '===')
hist = r.get('clarification_history', [])
if hist:
    print('Asked:', hist[0][0])
    print('Answer:', hist[0][3])
else:
    print('(no question asked)')
print()
print('Code:')
print(r.get('prompt_result', '').strip())
if not r['success']:
    print()
    print('Test result:')
    print(r.get('test_result', ''))
"
