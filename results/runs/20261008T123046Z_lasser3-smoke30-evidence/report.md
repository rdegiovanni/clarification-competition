# Run report — LAASeR3Algorithm (2026-10-08T12:32:44+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `0f53166` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/lasser3.py |
| Model | openai/gpt-4.1-mini |
| Temperature | 0.7 (SDK default) |
| Split / dataset | demo (smoke(classes=Mbpp,HumanEval,n=30)) |
| Tasks evaluated | 30 |
| Unit tests (tests/) | PASSED |

## Unit tests

All offline regression tests passed (`tests/`, no network/Docker — these catch exception-handling bugs that the live benchmark may not trigger).

## Official competition metrics

Computed with `evaluate_responses.py`'s own `_compute_output_row` / `_turn_discounted_sucess` / `_normalized_discounted_cumulative_gain` — the same code a real leaderboard submission uses.

| Metric | Value | Meaning |
|---|---|---|
| **TDS** (ranking metric) | 0.5280 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.3333 | clarification quality — higher is better |
| Pass@1 | 53.33% | raw pass rate |
| Clarification rate | 33.33% | % tasks where ≥1 question was asked |
| Over-asking rate | 0.00% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.001416 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `0f53166` at 2026-10-08T12:29:23+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.6722 | 0.5280 | ▼ -0.1442 |
| nDCG | 1.0000 | 0.3333 | ▼ -0.6667 |
| Pass@1 | 0.7000 | 0.5333 | ▼ -0.1667 |
| Clarification rate | 1.0000 | 0.3333 | ▼ -0.6667 |
| Over-asking rate | 1.0000 | 0.0000 | ▼ -1.0000 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| → | **LAASeR3Algorithm (this run)** | us | openai/gpt-4.1-mini | **0.5280** |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 5 | 15 | 33.33% |
| HumanEval | 11 | 15 | 73.33% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 9 |
| code ran but failed with an unhandled error | 4 |
| function name mismatch (NameError calling the entry point) | 1 |

## Failing task IDs

HumanEval/113, HumanEval/38, HumanEval/55, HumanEval/86, Mbpp/107, Mbpp/128, Mbpp/159, Mbpp/214, Mbpp/218, Mbpp/336, Mbpp/633, Mbpp/670, Mbpp/776, Mbpp/968

## Suggested next steps

- Mbpp pass rate (33.33%) is notably weaker than HumanEval (73.33%) — look at Mbpp failures first.
