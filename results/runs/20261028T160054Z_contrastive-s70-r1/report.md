# Run report — LAASeR_Evolution (2026-10-28T16:04:36+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `f98a712` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/LAASeR_Contrastive_Specs.py |
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
| **TDS** (ranking metric) | 0.3715 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.7429 | clarification quality — higher is better |
| Pass@1 | 38.57% | raw pass rate |
| Clarification rate | 95.71% | % tasks where ≥1 question was asked |
| Over-asking rate | 87.50% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.002515 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `f98a712` at 2026-10-28T16:03:27+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.3572 | 0.3715 | ▲ +0.0143 |
| nDCG | 0.7571 | 0.7429 | ▼ -0.0142 |
| Pass@1 | 0.3714 | 0.3857 | ▲ +0.0143 |
| Clarification rate | 0.9714 | 0.9571 | ▼ -0.0143 |
| Over-asking rate | 0.9375 | 0.8750 | ▼ -0.0625 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |
| → | **LAASeR_Evolution (this run)** | us | openai/gpt-4.1-mini | **0.3715** |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 12 | 39 | 30.77% |
| HumanEval | 15 | 31 | 48.39% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 25 |
| code ran but failed with an unhandled error | 18 |

## Failing task IDs

HumanEval/115, HumanEval/117, HumanEval/139, HumanEval/142, HumanEval/145, HumanEval/15, HumanEval/161, HumanEval/17, HumanEval/22, HumanEval/36, HumanEval/40, HumanEval/50, HumanEval/6, HumanEval/65, HumanEval/86, HumanEval/98, Mbpp/128, Mbpp/143, Mbpp/215, Mbpp/229, Mbpp/26, Mbpp/274, Mbpp/349, Mbpp/368, Mbpp/371, Mbpp/374, Mbpp/388, Mbpp/390, Mbpp/559, Mbpp/592, Mbpp/617, Mbpp/619, Mbpp/651, Mbpp/719, Mbpp/748, Mbpp/759, Mbpp/782, Mbpp/81, Mbpp/855, Mbpp/868, Mbpp/876, Mbpp/888, Mbpp/90

## Suggested next steps

- Over-asking rate is 87.50% — the algorithm is questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering.
- Mbpp pass rate (30.77%) is notably weaker than HumanEval (48.39%) — look at Mbpp failures first.
