# Run report — LAASeR_PinpointSMT (2026-10-21T14:08:14+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `9a180d4` (dirty — uncommitted changes) |
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
| **TDS** (ranking metric) | 0.6464 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.8714 | clarification quality — higher is better |
| Pass@1 | 67.14% | raw pass rate |
| Clarification rate | 95.71% | % tasks where ≥1 question was asked |
| Over-asking rate | 87.50% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.005721 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `9a180d4` at 2026-10-20T16:20:20+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.5384 | 0.6464 | ▲ +0.1080 |
| nDCG | 0.7714 | 0.8714 | ▲ +0.1000 |
| Pass@1 | 0.5571 | 0.6714 | ▲ +0.1143 |
| Clarification rate | 0.9000 | 0.9571 | ▲ +0.0571 |
| Over-asking rate | 0.6875 | 0.8750 | ▲ +0.1875 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| → | **LAASeR_PinpointSMT (this run)** | us | openai/gpt-4.1-mini | **0.6464** |
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 23 | 39 | 58.97% |
| HumanEval | 24 | 31 | 77.42% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 16 |
| code ran but failed with an unhandled error | 7 |

## Failing task IDs

HumanEval/139, HumanEval/145, HumanEval/15, HumanEval/17, HumanEval/82, HumanEval/86, HumanEval/98, Mbpp/128, Mbpp/143, Mbpp/229, Mbpp/26, Mbpp/349, Mbpp/371, Mbpp/374, Mbpp/390, Mbpp/559, Mbpp/617, Mbpp/651, Mbpp/719, Mbpp/748, Mbpp/759, Mbpp/81, Mbpp/888

## Suggested next steps

- Over-asking rate is 87.50% — the algorithm is questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering.
- Mbpp pass rate (58.97%) is notably weaker than HumanEval (77.42%) — look at Mbpp failures first.
