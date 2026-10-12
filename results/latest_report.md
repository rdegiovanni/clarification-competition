# Run report — LAASeR_Pinpoint (2026-10-12T09:57:57+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `343b29b` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_pinpoint.py |
| Model | openai/gpt-4.1-mini |
| Temperature | 0.7 (SDK default) |
| Split / dataset | demo (smoke(source=val,classes=Mbpp,HumanEval,n=60)) |
| Tasks evaluated | 60 |
| Unit tests (tests/) | PASSED |

## Unit tests

All offline regression tests passed (`tests/`, no network/Docker — these catch exception-handling bugs that the live benchmark may not trigger).

## Official competition metrics

Computed with `evaluate_responses.py`'s own `_compute_output_row` / `_turn_discounted_sucess` / `_normalized_discounted_cumulative_gain` — the same code a real leaderboard submission uses.

| Metric | Value | Meaning |
|---|---|---|
| **TDS** (ranking metric) | 0.7535 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.8833 | clarification quality — higher is better |
| Pass@1 | 78.33% | raw pass rate |
| Clarification rate | 96.67% | % tasks where ≥1 question was asked |
| Over-asking rate | 87.50% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.001063 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `343b29b` at 2026-10-12T09:55:30+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.7375 | 0.7535 | ▲ +0.0160 |
| nDCG | 0.8500 | 0.8833 | ▲ +0.0333 |
| Pass@1 | 0.7667 | 0.7833 | ▲ +0.0166 |
| Clarification rate | 0.9667 | 0.9667 | = +0.0000 |
| Over-asking rate | 0.9375 | 0.8750 | ▼ -0.0625 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| → | **LAASeR_Pinpoint (this run)** | us | openai/gpt-4.1-mini | **0.7535** |
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 22 | 30 | 73.33% |
| HumanEval | 25 | 30 | 83.33% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 10 |
| code ran but failed with an unhandled error | 3 |

## Failing task IDs

HumanEval/131, HumanEval/145, HumanEval/36, HumanEval/57, HumanEval/98, Mbpp/128, Mbpp/160, Mbpp/285, Mbpp/371, Mbpp/374, Mbpp/390, Mbpp/465, Mbpp/715

## Suggested next steps

- Over-asking rate is 87.50% — the algorithm is questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering.
