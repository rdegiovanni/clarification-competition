#!/usr/bin/env bash
# Runs the whole pipeline end-to-end and writes a Markdown report:
#   1. offline unit tests (tests/)
#   2. generate_responses.py   (run the algorithm against the benchmark)
#   3. evaluate_responses.py   (official TDS/nDCG/Pass@1/etc. scoring)
#   4. scripts/make_report.py  (Markdown report + results/history.csv row)
#
# Usage: scripts/evaluate.sh [options]
# Run with --help for the full option list.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

CLARIFY_PY="clarify/algorithms/LAASeRAlgorithm.py"
LANGUAGE_MODEL="${LANGUAGE_MODEL:-anthropic/claude-sonnet-5}"
SPLIT=""
DATASET_PATH=""
MAX_WORKERS=4
TEMPERATURE=""
LABEL=""
EXTRA_GEN_ARGS=""

usage() {
  cat <<'EOF'
Usage: scripts/evaluate.sh [options]

  --clarify-py PATH       Algorithm file to evaluate (default: clarify/algorithms/LAASeRAlgorithm.py)
  --language-model MODEL  LiteLLM model string (default: $LANGUAGE_MODEL env var, or anthropic/claude-sonnet-5)
  --split train|val       Use the official train/validation split instead of the 30-task demo set
  --dataset-path PATH     Custom dataset path (ignored if --split is given)
  --max-workers N         Parallel workers for generation/evaluation (default: 4)
  --temperature T         Sampling temperature forwarded to generate_responses.py
  --label NAME            Suffix for the run folder under results/runs/ (default: derived from --clarify-py)
  --extra-gen-args "..."  Extra args forwarded verbatim to generate_responses.py
  -h, --help              Show this help

Credentials: sources .env (gitignored) if present, so ANTHROPIC_API_KEY/ANTHROPIC_API_BASE
point at whatever is configured there before falling back to the current shell environment.

Output: results/runs/<timestamp>_<label>/{unittest.log,generate.log,evaluate.log,
generate.jsonl,results.jsonl,report.md}, plus results/latest_report.md and a new row
appended to results/history.csv.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --clarify-py) CLARIFY_PY="$2"; shift 2 ;;
    --language-model) LANGUAGE_MODEL="$2"; shift 2 ;;
    --split) SPLIT="$2"; shift 2 ;;
    --dataset-path) DATASET_PATH="$2"; shift 2 ;;
    --max-workers) MAX_WORKERS="$2"; shift 2 ;;
    --temperature) TEMPERATURE="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    --extra-gen-args) EXTRA_GEN_ARGS="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ -z "$LABEL" ]]; then
  LABEL="$(basename "$CLARIFY_PY" .py)"
fi

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="results/runs/${TIMESTAMP}_${LABEL}"
mkdir -p "$RUN_DIR"

echo "== 1/4: unit tests (tests/) =="
UNITTEST_STATUS="PASSED"
if ! uv run python -m unittest discover -s tests -v > "$RUN_DIR/unittest.log" 2>&1; then
  UNITTEST_STATUS="FAILED"
  echo "!! Unit tests FAILED — see $RUN_DIR/unittest.log. Continuing with the benchmark run anyway."
fi
echo "   status: $UNITTEST_STATUS"

GEN_PATH="$RUN_DIR/generate.jsonl"
RESULTS_PATH="$RUN_DIR/results.jsonl"

GEN_CMD=(uv run python generate_responses.py "$CLARIFY_PY" --output_path "$GEN_PATH" \
  --language_model "$LANGUAGE_MODEL" --max_workers "$MAX_WORKERS")
if [[ -n "$SPLIT" ]]; then
  GEN_CMD+=(--split "$SPLIT")
elif [[ -n "$DATASET_PATH" ]]; then
  GEN_CMD+=(--dataset_path "$DATASET_PATH")
fi
if [[ -n "$TEMPERATURE" ]]; then
  GEN_CMD+=(--temperature "$TEMPERATURE")
fi
if [[ -n "$EXTRA_GEN_ARGS" ]]; then
  # shellcheck disable=SC2206
  GEN_CMD+=($EXTRA_GEN_ARGS)
fi

echo "== 2/4: generating responses =="
echo "   ${GEN_CMD[*]}"
"${GEN_CMD[@]}" 2>&1 | tee "$RUN_DIR/generate.log"

echo "== 3/4: evaluating responses (official metrics) =="
EVAL_CMD=(uv run python evaluate_responses.py --generation_path "$GEN_PATH" \
  --output_path "$RESULTS_PATH" --max_workers "$MAX_WORKERS" --force_rerun)
if [[ -n "$SPLIT" ]]; then
  EVAL_CMD+=(--split "$SPLIT")
elif [[ -n "$DATASET_PATH" ]]; then
  EVAL_CMD+=(--benchmark_path "$DATASET_PATH")
fi

echo "   ${EVAL_CMD[*]}"
"${EVAL_CMD[@]}" 2>&1 | tee "$RUN_DIR/evaluate.log"

echo "== 4/4: building Markdown report =="
uv run python scripts/make_report.py \
  --run-dir "$RUN_DIR" \
  --clarify-py "$CLARIFY_PY" \
  --results-path "$RESULTS_PATH" \
  --split "$SPLIT" \
  --dataset-path "$DATASET_PATH" \
  --unittest-status "$UNITTEST_STATUS" \
  --unittest-log "$RUN_DIR/unittest.log" \
  --temperature "$TEMPERATURE"

echo ""
echo "Done. Report: $RUN_DIR/report.md (also results/latest_report.md)"
