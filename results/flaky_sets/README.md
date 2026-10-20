# Flaky smoke tasks (2026-10-15 snapshot)

`mbpp_flaky.jsonl` (12 tasks) and `humaneval_flaky.jsonl` (10 tasks): the tasks of smoke-70
(`--smoke-source val --smoke-size 70 --smoke-seed 42`, `openai/gpt-4.1-mini`) whose outcome
flipped between runs of `laaser_pinpoint.py`, `laaser_pinpoint_smt.py` or
`laaser_pinpoint_smt_3.py`, with exactly the prompts the smoke runs used. Built from the
history as of the 2 `smt_3` runs of 09:15 and 09:34 UTC; the determinism runs `det-*` of
2026-10-15 use this fixed set.

Regenerate (the set grows as more runs land in `results/history.csv`; with the 2 later
`v7-*-r1` runs it also includes HumanEval/6):

```bash
uv run python scripts/find_flaky_tasks.py --write-dataset results/flaky_sets \
  --files laaser_pinpoint.py laaser_pinpoint_smt.py laaser_pinpoint_smt_3.py
```

Run one variant on it (one `evaluate.sh` per benchmark class):

```bash
PYTHONINTMAXSTRDIGITS=0 scripts/evaluate.sh --clarify-py clarify/algorithms/laaser_pinpoint_smt_3.py \
  --language-model openai/gpt-4.1-mini --dataset-path results/flaky_sets/mbpp_flaky.jsonl --label <name>-mbpp
```

`scripts/measure_determinism.sh` runs v7 defaults vs. voting, 3 times each, on both files.
