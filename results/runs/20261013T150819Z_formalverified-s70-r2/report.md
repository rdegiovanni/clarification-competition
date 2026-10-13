# Run report — LAASeR_FormalVerified (2026-10-13T15:11:32+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `4c47165` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_formal_verified.py |
| Model | openai/gpt-4.1-mini |
| Temperature | 0.7 (SDK default) |
| Split / dataset | demo (smoke(source=val,classes=Mbpp,HumanEval,n=70)) |
| Tasks evaluated | 70 |
| Unit tests (tests/) | PASSED |

## Unit tests

All offline regression tests passed (`tests/`, no network/Docker — these catch exception-handling bugs that the live benchmark may not trigger).

## Official competition metrics

Computed with `evaluate_responses.py`'s own `_compute_output_row` / `_turn_discounted_sucess` / `_normalized_discounted_cumulative_gain` — the same code a real leaderboard submission uses.

| Metric | Value | Meaning |
|---|---|---|
| **TDS** (ranking metric) | 0.6636 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.7429 | clarification quality — higher is better |
| Pass@1 | 68.57% | raw pass rate |
| Clarification rate | 80.00% | % tasks where ≥1 question was asked |
| Over-asking rate | 75.00% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.001221 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `4c47165` at 2026-10-13T15:07:55+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.6350 | 0.6636 | ▲ +0.0286 |
| nDCG | 0.7714 | 0.7429 | ▼ -0.0285 |
| Pass@1 | 0.6571 | 0.6857 | ▲ +0.0286 |
| Clarification rate | 0.7857 | 0.8000 | ▲ +0.0143 |
| Over-asking rate | 0.8750 | 0.7500 | ▼ -0.1250 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| → | **LAASeR_FormalVerified (this run)** | us | openai/gpt-4.1-mini | **0.6636** |
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 23 | 39 | 58.97% |
| HumanEval | 25 | 31 | 80.65% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 13 |
| code ran but failed with an unhandled error | 9 |

## Failing task IDs

HumanEval/139, HumanEval/145, HumanEval/15, HumanEval/65, HumanEval/86, HumanEval/98, Mbpp/128, Mbpp/143, Mbpp/229, Mbpp/26, Mbpp/349, Mbpp/368, Mbpp/371, Mbpp/374, Mbpp/390, Mbpp/559, Mbpp/617, Mbpp/719, Mbpp/748, Mbpp/759, Mbpp/81, Mbpp/888

## Suggested next steps

- Over-asking rate is 75.00% — the algorithm is questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering.
- Mbpp pass rate (58.97%) is notably weaker than HumanEval (80.65%) — look at Mbpp failures first.
