#!/bin/zsh
# One HumanEval/65 variant per dataset file (the loader keeps one variant per task id).
# Usage: results/format_sets/he65/run.sh <label> <extra generate args...>
set -u
label=$1; shift
out=results/format_sets/he65/$label; mkdir -p $out
for f in results/format_sets/he65/humaneval65_*.jsonl; do
  i=${${f:t:r}##*_}
  (uv run python generate_responses.py clarify/algorithms/laaser_pinpoint_smt_3.py --output_path $out/gen_$i.jsonl \
     --language_model openai/gpt-4.1-mini --max_workers 1 --dataset_path $f "$@" > $out/gen_$i.log 2>&1 &&
   uv run python evaluate_responses.py --generation_path $out/gen_$i.jsonl --output_path $out/res_$i.jsonl \
     --max_workers 1 --force_rerun --benchmark_path $f > $out/eval_$i.log 2>&1) &
done
wait
cat $out/res_*.jsonl > $out/results.jsonl
