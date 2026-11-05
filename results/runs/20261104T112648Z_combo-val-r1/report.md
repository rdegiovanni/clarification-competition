# Run report — LAASeR_PinpointChecks (2026-11-04T12:15:57+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `15913f1` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_pinpoint_checks.py |
| Model | openai/gpt-4.1-mini |
| Temperature | 0.7 (SDK default) |
| Split / dataset | val (split:val) |
| Tasks evaluated | 770 |
| Unit tests (tests/) | FAILED |

## Unit tests

**Unit tests did not pass** (`FAILED`). See `unittest.log` in this run's folder before trusting the benchmark numbers below.

## Official competition metrics

Computed with `evaluate_responses.py`'s own `_compute_output_row` / `_turn_discounted_sucess` / `_normalized_discounted_cumulative_gain` — the same code a real leaderboard submission uses.

| Metric | Value | Meaning |
|---|---|---|
| **TDS** (ranking metric) | 0.7370 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.8896 | clarification quality — higher is better |
| Pass@1 | 76.75% | raw pass rate |
| Clarification rate | 100.00% | % tasks where ≥1 question was asked |
| Over-asking rate | 100.00% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.003524 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `15913f1` at 2026-11-04T11:55:47+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.7047 | 0.7370 | ▲ +0.0323 |
| nDCG | 0.8494 | 0.8896 | ▲ +0.0402 |
| Pass@1 | 0.7325 | 0.7675 | ▲ +0.0350 |
| Clarification rate | 0.9623 | 1.0000 | ▲ +0.0377 |
| Over-asking rate | 0.9016 | 1.0000 | ▲ +0.0984 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| → | **LAASeR_PinpointChecks (this run)** | us | openai/gpt-4.1-mini | **0.7370** |
| 1 | GatedClarification | — | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 303 | 420 | 72.14% |
| HumanEval | 288 | 350 | 82.29% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 146 |
| code ran but failed with an unhandled error | 31 |
| evalplus execution timeout | 1 |
| function name mismatch (NameError calling the entry point) | 1 |

## Failing task IDs

HumanEval/109, HumanEval/109, HumanEval/115, HumanEval/115, HumanEval/117, HumanEval/117, HumanEval/120, HumanEval/131, HumanEval/133, HumanEval/133, HumanEval/142, HumanEval/142, HumanEval/145, HumanEval/145, HumanEval/145, HumanEval/145, HumanEval/145, HumanEval/145, HumanEval/15, HumanEval/15, HumanEval/15, HumanEval/161, HumanEval/161, HumanEval/161, HumanEval/161, HumanEval/161, HumanEval/17, HumanEval/17, HumanEval/17, HumanEval/22, HumanEval/22, HumanEval/22, HumanEval/3, HumanEval/40, HumanEval/50, HumanEval/50, HumanEval/50, HumanEval/50, HumanEval/57, HumanEval/57, HumanEval/6, HumanEval/60, HumanEval/65, HumanEval/65, HumanEval/65, HumanEval/65, HumanEval/65, HumanEval/66, HumanEval/66, HumanEval/69, HumanEval/72, HumanEval/72, HumanEval/72, HumanEval/73, HumanEval/74, HumanEval/82, HumanEval/86, HumanEval/86, HumanEval/86, HumanEval/86, HumanEval/98, HumanEval/98, Mbpp/100, Mbpp/100, Mbpp/105, Mbpp/128, Mbpp/128, Mbpp/128, Mbpp/128, Mbpp/128, Mbpp/128, Mbpp/160, Mbpp/160, Mbpp/160, Mbpp/160, Mbpp/160, Mbpp/160, Mbpp/160, Mbpp/167, Mbpp/215, Mbpp/215, Mbpp/239, Mbpp/239, Mbpp/239, Mbpp/239, Mbpp/239, Mbpp/239, Mbpp/271, Mbpp/274, Mbpp/285, Mbpp/285, Mbpp/285, Mbpp/285, Mbpp/285, Mbpp/301, Mbpp/301, Mbpp/345, Mbpp/349, Mbpp/349, Mbpp/353, Mbpp/364, Mbpp/368, Mbpp/368, Mbpp/371, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/380, Mbpp/390, Mbpp/390, Mbpp/390, Mbpp/390, Mbpp/390, Mbpp/390, Mbpp/433, Mbpp/465, Mbpp/465, Mbpp/465, Mbpp/471, Mbpp/471, Mbpp/550, Mbpp/550, Mbpp/550, Mbpp/550, Mbpp/550, Mbpp/619, Mbpp/634, Mbpp/644, Mbpp/651, Mbpp/651, Mbpp/651, Mbpp/678, Mbpp/678, Mbpp/715, Mbpp/715, Mbpp/719, Mbpp/719, Mbpp/719, Mbpp/719, Mbpp/719, Mbpp/719, Mbpp/719, Mbpp/72, Mbpp/722, Mbpp/722, Mbpp/722, Mbpp/722, Mbpp/722, Mbpp/722, Mbpp/748, Mbpp/748, Mbpp/748, Mbpp/748, Mbpp/748, Mbpp/748, Mbpp/782, Mbpp/792, Mbpp/81, Mbpp/81, Mbpp/81, Mbpp/827, Mbpp/855, Mbpp/883, Mbpp/888, Mbpp/888, Mbpp/907, Mbpp/907, Mbpp/907, Mbpp/907, Mbpp/95, Mbpp/95, Mbpp/960, Mbpp/960, Mbpp/960, Mbpp/960

## Suggested next steps

- Over-asking rate is 100.00% — the algorithm is questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering.
