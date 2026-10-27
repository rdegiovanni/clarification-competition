# Run report — LAASeR_PinpointSMT (2026-10-27T15:41:13+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `45cdb15` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_pinpoint_smt_3.py |
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
| **TDS** (ranking metric) | 0.7070 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.8597 | clarification quality — higher is better |
| Pass@1 | 73.51% | raw pass rate |
| Clarification rate | 96.88% | % tasks where ≥1 question was asked |
| Over-asking rate | 91.71% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.003507 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `9891cf8` at 2026-10-26T17:44:18+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.7144 | 0.7070 | ▼ -0.0074 |
| nDCG | 0.8545 | 0.8597 | ▲ +0.0052 |
| Pass@1 | 0.7429 | 0.7351 | ▼ -0.0078 |
| Clarification rate | 0.9662 | 0.9688 | ▲ +0.0026 |
| Over-asking rate | 0.9171 | 0.9171 | = +0.0000 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| → | **LAASeR_PinpointSMT (this run)** | us | openai/gpt-4.1-mini | **0.7070** |
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 279 | 420 | 66.43% |
| HumanEval | 287 | 350 | 82.00% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 150 |
| code ran but failed with an unhandled error | 52 |
| evalplus execution timeout | 1 |
| function name mismatch (NameError calling the entry point) | 1 |

## Failing task IDs

HumanEval/109, HumanEval/109, HumanEval/115, HumanEval/115, HumanEval/117, HumanEval/117, HumanEval/117, HumanEval/120, HumanEval/131, HumanEval/131, HumanEval/133, HumanEval/133, HumanEval/133, HumanEval/142, HumanEval/145, HumanEval/145, HumanEval/145, HumanEval/145, HumanEval/15, HumanEval/15, HumanEval/15, HumanEval/15, HumanEval/161, HumanEval/161, HumanEval/161, HumanEval/17, HumanEval/17, HumanEval/17, HumanEval/22, HumanEval/22, HumanEval/37, HumanEval/37, HumanEval/4, HumanEval/40, HumanEval/50, HumanEval/50, HumanEval/57, HumanEval/6, HumanEval/6, HumanEval/6, HumanEval/65, HumanEval/65, HumanEval/65, HumanEval/65, HumanEval/65, HumanEval/65, HumanEval/69, HumanEval/69, HumanEval/69, HumanEval/72, HumanEval/72, HumanEval/72, HumanEval/73, HumanEval/74, HumanEval/74, HumanEval/74, HumanEval/86, HumanEval/86, HumanEval/86, HumanEval/98, HumanEval/98, HumanEval/98, HumanEval/98, Mbpp/100, Mbpp/104, Mbpp/105, Mbpp/105, Mbpp/128, Mbpp/128, Mbpp/128, Mbpp/128, Mbpp/128, Mbpp/128, Mbpp/160, Mbpp/160, Mbpp/160, Mbpp/160, Mbpp/160, Mbpp/215, Mbpp/215, Mbpp/215, Mbpp/239, Mbpp/239, Mbpp/239, Mbpp/239, Mbpp/239, Mbpp/271, Mbpp/274, Mbpp/285, Mbpp/285, Mbpp/285, Mbpp/285, Mbpp/301, Mbpp/301, Mbpp/301, Mbpp/345, Mbpp/349, Mbpp/349, Mbpp/349, Mbpp/349, Mbpp/349, Mbpp/353, Mbpp/353, Mbpp/368, Mbpp/371, Mbpp/371, Mbpp/371, Mbpp/371, Mbpp/371, Mbpp/371, Mbpp/371, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/380, Mbpp/380, Mbpp/380, Mbpp/380, Mbpp/380, Mbpp/390, Mbpp/390, Mbpp/390, Mbpp/390, Mbpp/390, Mbpp/390, Mbpp/433, Mbpp/433, Mbpp/465, Mbpp/471, Mbpp/471, Mbpp/550, Mbpp/550, Mbpp/550, Mbpp/550, Mbpp/550, Mbpp/592, Mbpp/592, Mbpp/592, Mbpp/619, Mbpp/619, Mbpp/619, Mbpp/619, Mbpp/619, Mbpp/634, Mbpp/634, Mbpp/644, Mbpp/651, Mbpp/651, Mbpp/651, Mbpp/678, Mbpp/678, Mbpp/715, Mbpp/715, Mbpp/719, Mbpp/719, Mbpp/719, Mbpp/719, Mbpp/719, Mbpp/719, Mbpp/719, Mbpp/722, Mbpp/722, Mbpp/722, Mbpp/722, Mbpp/722, Mbpp/722, Mbpp/748, Mbpp/748, Mbpp/748, Mbpp/748, Mbpp/748, Mbpp/748, Mbpp/782, Mbpp/792, Mbpp/792, Mbpp/792, Mbpp/81, Mbpp/81, Mbpp/81, Mbpp/81, Mbpp/81, Mbpp/81, Mbpp/827, Mbpp/883, Mbpp/888, Mbpp/888, Mbpp/888, Mbpp/888, Mbpp/907, Mbpp/907, Mbpp/907, Mbpp/907, Mbpp/95, Mbpp/95, Mbpp/95, Mbpp/960, Mbpp/960, Mbpp/960, Mbpp/960, Mbpp/960

## Suggested next steps

- Over-asking rate is 91.71% — the algorithm is questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering.
- Mbpp pass rate (66.43%) is notably weaker than HumanEval (82.00%) — look at Mbpp failures first.
