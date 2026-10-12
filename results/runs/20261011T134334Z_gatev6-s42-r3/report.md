# Run report — LAASeR_GateV6 (2026-10-11T13:46:27+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `316febc` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_gate_v6.py |
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
| **TDS** (ranking metric) | 0.6521 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.4333 | clarification quality — higher is better |
| Pass@1 | 66.67% | raw pass rate |
| Clarification rate | 53.33% | % tasks where ≥1 question was asked |
| Over-asking rate | 0.00% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.003368 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `316febc` at 2026-10-11T13:43:24+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.7174 | 0.6521 | ▼ -0.0653 |
| nDCG | 0.4000 | 0.4333 | ▲ +0.0333 |
| Pass@1 | 0.7333 | 0.6667 | ▼ -0.0666 |
| Clarification rate | 0.5333 | 0.5333 | = +0.0000 |
| Over-asking rate | 0.0000 | 0.0000 | = +0.0000 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| → | **LAASeR_GateV6 (this run)** | us | openai/gpt-4.1-mini | **0.6521** |
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 8 | 15 | 53.33% |
| HumanEval | 12 | 15 | 80.00% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 5 |
| code ran but failed with an unhandled error | 5 |

## Failing task IDs

HumanEval/139, HumanEval/154, HumanEval/55, Mbpp/143, Mbpp/229, Mbpp/26, Mbpp/559, Mbpp/755, Mbpp/759, Mbpp/90

## Suggested next steps

- Mbpp pass rate (53.33%) is notably weaker than HumanEval (80.00%) — look at Mbpp failures first.
