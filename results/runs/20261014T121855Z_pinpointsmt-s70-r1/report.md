# Run report — LAASeR_PinpointSMT (2026-10-14T12:21:11+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `557d02d` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_pinpoint_smt.py |
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
| **TDS** (ranking metric) | 0.6179 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.8571 | clarification quality — higher is better |
| Pass@1 | 64.29% | raw pass rate |
| Clarification rate | 98.57% | % tasks where ≥1 question was asked |
| Over-asking rate | 100.00% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.001052 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `557d02d` at 2026-10-14T12:18:32+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.6470 | 0.6179 | ▼ -0.0291 |
| nDCG | 0.8429 | 0.8571 | ▲ +0.0142 |
| Pass@1 | 0.6714 | 0.6429 | ▼ -0.0285 |
| Clarification rate | 0.9429 | 0.9857 | ▲ +0.0428 |
| Over-asking rate | 0.7500 | 1.0000 | ▲ +0.2500 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| → | **LAASeR_PinpointSMT (this run)** | us | openai/gpt-4.1-mini | **0.6179** |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 21 | 39 | 53.85% |
| HumanEval | 24 | 31 | 77.42% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 18 |
| code ran but failed with an unhandled error | 7 |

## Failing task IDs

HumanEval/115, HumanEval/139, HumanEval/142, HumanEval/145, HumanEval/15, HumanEval/86, HumanEval/98, Mbpp/128, Mbpp/143, Mbpp/229, Mbpp/26, Mbpp/349, Mbpp/368, Mbpp/371, Mbpp/374, Mbpp/390, Mbpp/559, Mbpp/592, Mbpp/617, Mbpp/619, Mbpp/719, Mbpp/748, Mbpp/759, Mbpp/81, Mbpp/888

## Suggested next steps

- Over-asking rate is 100.00% — the algorithm is questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering.
- Mbpp pass rate (53.85%) is notably weaker than HumanEval (77.42%) — look at Mbpp failures first.
