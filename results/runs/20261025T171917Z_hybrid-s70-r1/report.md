# Run report — LAASeR_PinpointSMT (2026-10-25T17:22:27+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `3f5ecb6` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_pinpoint_smt_3.py |
| Model | openai/gpt-4.1-mini |
| Temperature | 0.7 (SDK default) |
| Split / dataset | demo (smoke(source=val,classes=Mbpp,HumanEval,n=70)) |
| Tasks evaluated | 70 |
| Unit tests (tests/) | FAILED |

## Unit tests

**Unit tests did not pass** (`FAILED`). See `unittest.log` in this run's folder before trusting the benchmark numbers below.

## Official competition metrics

Computed with `evaluate_responses.py`'s own `_compute_output_row` / `_turn_discounted_sucess` / `_normalized_discounted_cumulative_gain` — the same code a real leaderboard submission uses.

| Metric | Value | Meaning |
|---|---|---|
| **TDS** (ranking metric) | 0.6607 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.8286 | clarification quality — higher is better |
| Pass@1 | 68.57% | raw pass rate |
| Clarification rate | 94.29% | % tasks where ≥1 question was asked |
| Over-asking rate | 81.25% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.002739 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `5259e1b` at 2026-10-24T14:13:05+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.6870 | 0.6607 | ▼ -0.0263 |
| nDCG | 0.8429 | 0.8286 | ▼ -0.0143 |
| Pass@1 | 0.7143 | 0.6857 | ▼ -0.0286 |
| Clarification rate | 0.9714 | 0.9429 | ▼ -0.0285 |
| Over-asking rate | 0.9375 | 0.8125 | ▼ -0.1250 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| → | **LAASeR_PinpointSMT (this run)** | us | openai/gpt-4.1-mini | **0.6607** |
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 21 | 39 | 53.85% |
| HumanEval | 27 | 31 | 87.10% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 12 |
| code ran but failed with an unhandled error | 10 |

## Failing task IDs

HumanEval/139, HumanEval/145, HumanEval/15, HumanEval/98, Mbpp/104, Mbpp/128, Mbpp/143, Mbpp/215, Mbpp/229, Mbpp/26, Mbpp/349, Mbpp/368, Mbpp/371, Mbpp/374, Mbpp/390, Mbpp/559, Mbpp/617, Mbpp/719, Mbpp/748, Mbpp/759, Mbpp/81, Mbpp/888

## Suggested next steps

- Over-asking rate is 81.25% — the algorithm is questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering.
- Mbpp pass rate (53.85%) is notably weaker than HumanEval (87.10%) — look at Mbpp failures first.
