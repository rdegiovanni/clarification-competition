# Run report — LAASeR_PinpointSMT (2026-10-21T13:54:57+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `9a180d4` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_pinpoint_smt_3.py |
| Model | openai/gpt-4.1-mini |
| Temperature | 0.7 (SDK default) |
| Split / dataset | demo (results/multireq_sets/mbpp_multireq.jsonl) |
| Tasks evaluated | 13 |
| Unit tests (tests/) | FAILED |

## Unit tests

**Unit tests did not pass** (`FAILED`). See `unittest.log` in this run's folder before trusting the benchmark numbers below.

## Official competition metrics

Computed with `evaluate_responses.py`'s own `_compute_output_row` / `_turn_discounted_sucess` / `_normalized_discounted_cumulative_gain` — the same code a real leaderboard submission uses.

| Metric | Value | Meaning |
|---|---|---|
| **TDS** (ranking metric) | 0.4432 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 1.0000 | clarification quality — higher is better |
| Pass@1 | 46.15% | raw pass rate |
| Clarification rate | 100.00% | % tasks where ≥1 question was asked |
| Over-asking rate | 0.00% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.004867 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `9a180d4` at 2026-10-21T13:47:24+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.2955 | 0.4432 | ▲ +0.1477 |
| nDCG | 0.9231 | 1.0000 | ▲ +0.0769 |
| Pass@1 | 0.3077 | 0.4615 | ▲ +0.1538 |
| Clarification rate | 1.0000 | 1.0000 | = +0.0000 |
| Over-asking rate | 0.0000 | 0.0000 | = +0.0000 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |
| → | **LAASeR_PinpointSMT (this run)** | us | openai/gpt-4.1-mini | **0.4432** |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 6 | 13 | 46.15% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 5 |
| code ran but failed with an unhandled error | 2 |

## Failing task IDs

Mbpp/128, Mbpp/349, Mbpp/371, Mbpp/374, Mbpp/719, Mbpp/748, Mbpp/81

## Suggested next steps

- No obvious red flag from this single run; compare the TDS trend across multiple runs in `results/history.csv` before concluding anything changed.
