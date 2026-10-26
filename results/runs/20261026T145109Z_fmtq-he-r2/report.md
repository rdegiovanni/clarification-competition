# Run report — LAASeR_PinpointSMT (2026-10-26T14:54:17+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `6cec41a` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_pinpoint_smt_3.py |
| Model | openai/gpt-4.1-mini |
| Temperature | 0.7 (SDK default) |
| Split / dataset | demo (results/format_sets/humaneval_format.jsonl) |
| Tasks evaluated | 19 |
| Unit tests (tests/) | FAILED |

## Unit tests

**Unit tests did not pass** (`FAILED`). See `unittest.log` in this run's folder before trusting the benchmark numbers below.

## Official competition metrics

Computed with `evaluate_responses.py`'s own `_compute_output_row` / `_turn_discounted_sucess` / `_normalized_discounted_cumulative_gain` — the same code a real leaderboard submission uses.

| Metric | Value | Meaning |
|---|---|---|
| **TDS** (ranking metric) | 0.3032 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.8947 | clarification quality — higher is better |
| Pass@1 | 31.58% | raw pass rate |
| Clarification rate | 100.00% | % tasks where ≥1 question was asked |
| Over-asking rate | 100.00% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.005197 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `6cec41a` at 2026-10-26T14:54:09+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.0505 | 0.3032 | ▲ +0.2527 |
| nDCG | 0.9474 | 0.8947 | ▼ -0.0527 |
| Pass@1 | 0.0526 | 0.3158 | ▲ +0.2632 |
| Clarification rate | 1.0000 | 1.0000 | = +0.0000 |
| Over-asking rate | 1.0000 | 1.0000 | = +0.0000 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |
| → | **LAASeR_PinpointSMT (this run)** | us | openai/gpt-4.1-mini | **0.3032** |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| HumanEval | 6 | 19 | 31.58% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 11 |
| code ran but failed with an unhandled error | 2 |

## Failing task IDs

HumanEval/133, HumanEval/145, HumanEval/22, HumanEval/4, HumanEval/40, HumanEval/57, HumanEval/6, HumanEval/60, HumanEval/65, HumanEval/72, HumanEval/74, HumanEval/86, HumanEval/98

## Suggested next steps

- Over-asking rate is 100.00% — the algorithm is questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering.
