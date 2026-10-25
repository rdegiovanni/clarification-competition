# Run report — LAASeR_PinpointSMT (2026-10-25T14:29:56+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `18bcea1` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_pinpoint_smt_3.py |
| Model | openai/gpt-4.1-mini |
| Temperature | 0.7 (SDK default) |
| Split / dataset | data/splits/validation_humaneval.txt (split:data/splits/validation_humaneval.txt) |
| Tasks evaluated | 350 |
| Unit tests (tests/) | FAILED |

## Unit tests

**Unit tests did not pass** (`FAILED`). See `unittest.log` in this run's folder before trusting the benchmark numbers below.

## Official competition metrics

Computed with `evaluate_responses.py`'s own `_compute_output_row` / `_turn_discounted_sucess` / `_normalized_discounted_cumulative_gain` — the same code a real leaderboard submission uses.

| Metric | Value | Meaning |
|---|---|---|
| **TDS** (ranking metric) | 0.7540 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.8829 | clarification quality — higher is better |
| Pass@1 | 78.29% | raw pass rate |
| Clarification rate | 93.43% | % tasks where ≥1 question was asked |
| Over-asking rate | 86.67% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.002034 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `e308dfd` at 2026-10-23T16:46:14+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.7618 | 0.7540 | ▼ -0.0078 |
| nDCG | 0.9171 | 0.8829 | ▼ -0.0342 |
| Pass@1 | 0.7914 | 0.7829 | ▼ -0.0085 |
| Clarification rate | 0.9514 | 0.9343 | ▼ -0.0171 |
| Over-asking rate | 0.9238 | 0.8667 | ▼ -0.0571 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| → | **LAASeR_PinpointSMT (this run)** | us | openai/gpt-4.1-mini | **0.7540** |
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| HumanEval | 274 | 350 | 78.29% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 72 |
| code ran but failed with an unhandled error | 4 |

## Failing task IDs

HumanEval/109, HumanEval/109, HumanEval/115, HumanEval/115, HumanEval/115, HumanEval/115, HumanEval/115, HumanEval/117, HumanEval/120, HumanEval/131, HumanEval/131, HumanEval/133, HumanEval/133, HumanEval/133, HumanEval/142, HumanEval/145, HumanEval/145, HumanEval/145, HumanEval/145, HumanEval/145, HumanEval/145, HumanEval/145, HumanEval/145, HumanEval/15, HumanEval/15, HumanEval/15, HumanEval/15, HumanEval/161, HumanEval/161, HumanEval/161, HumanEval/17, HumanEval/17, HumanEval/17, HumanEval/22, HumanEval/22, HumanEval/22, HumanEval/22, HumanEval/3, HumanEval/3, HumanEval/3, HumanEval/36, HumanEval/36, HumanEval/36, HumanEval/37, HumanEval/4, HumanEval/40, HumanEval/40, HumanEval/50, HumanEval/50, HumanEval/50, HumanEval/50, HumanEval/57, HumanEval/57, HumanEval/6, HumanEval/6, HumanEval/60, HumanEval/60, HumanEval/65, HumanEval/65, HumanEval/66, HumanEval/69, HumanEval/69, HumanEval/72, HumanEval/72, HumanEval/74, HumanEval/74, HumanEval/82, HumanEval/86, HumanEval/86, HumanEval/86, HumanEval/86, HumanEval/86, HumanEval/98, HumanEval/98, HumanEval/98, HumanEval/98

## Suggested next steps

- Over-asking rate is 86.67% — the algorithm is questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering.
