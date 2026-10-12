# Run report — LAASeR_GateV3 (2026-10-10T14:51:15+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `6bde6a1` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_gate_v3.py |
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
| **TDS** (ranking metric) | 0.6801 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.5667 | clarification quality — higher is better |
| Pass@1 | 70.00% | raw pass rate |
| Clarification rate | 60.00% | % tasks where ≥1 question was asked |
| Over-asking rate | 0.00% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.002325 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `6bde6a1` at 2026-10-10T14:48:45+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.6494 | 0.6801 | ▲ +0.0307 |
| nDCG | 0.6000 | 0.5667 | ▼ -0.0333 |
| Pass@1 | 0.6667 | 0.7000 | ▲ +0.0333 |
| Clarification rate | 0.6333 | 0.6000 | ▼ -0.0333 |
| Over-asking rate | 0.0000 | 0.0000 | = +0.0000 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| → | **LAASeR_GateV3 (this run)** | us | openai/gpt-4.1-mini | **0.6801** |
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 7 | 15 | 46.67% |
| HumanEval | 14 | 15 | 93.33% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but failed with an unhandled error | 6 |
| code ran but produced the wrong output | 3 |

## Failing task IDs

HumanEval/139, Mbpp/115, Mbpp/143, Mbpp/229, Mbpp/26, Mbpp/559, Mbpp/755, Mbpp/759, Mbpp/90

## Suggested next steps

- Mbpp pass rate (46.67%) is notably weaker than HumanEval (93.33%) — look at Mbpp failures first.
