# Run report — LAASeR_ConcreteQuestion (2026-10-09T15:34:36+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `082d0ae` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_concretequestion.py |
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
| **TDS** (ranking metric) | 0.6987 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.0667 | clarification quality — higher is better |
| Pass@1 | 70.00% | raw pass rate |
| Clarification rate | 10.00% | % tasks where ≥1 question was asked |
| Over-asking rate | 0.00% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.000327 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `082d0ae` at 2026-10-09T15:20:48+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.6653 | 0.6987 | ▲ +0.0334 |
| nDCG | 0.1000 | 0.0667 | ▼ -0.0333 |
| Pass@1 | 0.6667 | 0.7000 | ▲ +0.0333 |
| Clarification rate | 0.1000 | 0.1000 | = +0.0000 |
| Over-asking rate | 0.0000 | 0.0000 | = +0.0000 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| → | **LAASeR_ConcreteQuestion (this run)** | us | openai/gpt-4.1-mini | **0.6987** |
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 9 | 15 | 60.00% |
| HumanEval | 12 | 15 | 80.00% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but failed with an unhandled error | 5 |
| code ran but produced the wrong output | 3 |
| no python code block returned | 1 |

## Failing task IDs

HumanEval/139, HumanEval/154, HumanEval/55, Mbpp/143, Mbpp/229, Mbpp/26, Mbpp/559, Mbpp/755, Mbpp/759

## Suggested next steps

- Only 66.67% of clarification questions were rated high-quality (score 3) — review question phrasing against the Criticality/Search-space/Leakage/Atomicity/Objectivity criteria in the README.
- Mbpp pass rate (60.00%) is notably weaker than HumanEval (80.00%) — look at Mbpp failures first.
