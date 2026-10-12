# Run report — LAASeR_Gate (2026-10-09T16:51:43+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `8f23717` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_gate.py |
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
| **TDS** (ranking metric) | 0.6402 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.9667 | clarification quality — higher is better |
| Pass@1 | 66.67% | raw pass rate |
| Clarification rate | 100.00% | % tasks where ≥1 question was asked |
| Over-asking rate | 0.00% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.001294 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `8f23717` at 2026-10-09T16:48:30+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.6082 | 0.6402 | ▲ +0.0320 |
| nDCG | 1.0000 | 0.9667 | ▼ -0.0333 |
| Pass@1 | 0.6333 | 0.6667 | ▲ +0.0334 |
| Clarification rate | 1.0000 | 1.0000 | = +0.0000 |
| Over-asking rate | 0.0000 | 0.0000 | = +0.0000 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| → | **LAASeR_Gate (this run)** | us | openai/gpt-4.1-mini | **0.6402** |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 7 | 15 | 46.67% |
| HumanEval | 13 | 15 | 86.67% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 5 |
| code ran but failed with an unhandled error | 5 |

## Failing task IDs

HumanEval/139, HumanEval/50, Mbpp/143, Mbpp/229, Mbpp/251, Mbpp/26, Mbpp/559, Mbpp/755, Mbpp/759, Mbpp/90

## Suggested next steps

- Mbpp pass rate (46.67%) is notably weaker than HumanEval (86.67%) — look at Mbpp failures first.
