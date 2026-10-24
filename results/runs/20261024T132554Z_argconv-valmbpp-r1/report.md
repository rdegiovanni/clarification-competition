# Run report — LAASeR_PinpointSMT (2026-10-24T13:45:20+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `e308dfd` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_pinpoint_smt_3.py |
| Model | openai/gpt-4.1-mini |
| Temperature | 0.7 (SDK default) |
| Split / dataset | data/splits/validation_mbpp.txt (split:data/splits/validation_mbpp.txt) |
| Tasks evaluated | 420 |
| Unit tests (tests/) | FAILED |

## Unit tests

**Unit tests did not pass** (`FAILED`). See `unittest.log` in this run's folder before trusting the benchmark numbers below.

## Official competition metrics

Computed with `evaluate_responses.py`'s own `_compute_output_row` / `_turn_discounted_sucess` / `_normalized_discounted_cumulative_gain` — the same code a real leaderboard submission uses.

| Metric | Value | Meaning |
|---|---|---|
| **TDS** (ranking metric) | 0.6127 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.8071 | clarification quality — higher is better |
| Pass@1 | 63.81% | raw pass rate |
| Clarification rate | 92.38% | % tasks where ≥1 question was asked |
| Over-asking rate | 93.18% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.003247 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run

No earlier run recorded for this exact (algorithm, model, split, dataset) combination in `results/history.csv` — this is the first data point.

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| → | **LAASeR_PinpointSMT (this run)** | us | openai/gpt-4.1-mini | **0.6127** |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 268 | 420 | 63.81% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 66 |
| code ran but failed with an unhandled error | 53 |
| no python code block returned | 32 |
| evalplus execution timeout | 1 |

## Failing task IDs

Mbpp/105, Mbpp/105, Mbpp/128, Mbpp/128, Mbpp/128, Mbpp/128, Mbpp/128, Mbpp/128, Mbpp/128, Mbpp/160, Mbpp/160, Mbpp/160, Mbpp/167, Mbpp/215, Mbpp/215, Mbpp/215, Mbpp/215, Mbpp/239, Mbpp/239, Mbpp/239, Mbpp/239, Mbpp/239, Mbpp/239, Mbpp/239, Mbpp/271, Mbpp/274, Mbpp/285, Mbpp/285, Mbpp/285, Mbpp/285, Mbpp/301, Mbpp/301, Mbpp/301, Mbpp/345, Mbpp/349, Mbpp/353, Mbpp/368, Mbpp/368, Mbpp/368, Mbpp/371, Mbpp/371, Mbpp/371, Mbpp/371, Mbpp/371, Mbpp/371, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/380, Mbpp/380, Mbpp/380, Mbpp/380, Mbpp/388, Mbpp/390, Mbpp/390, Mbpp/390, Mbpp/390, Mbpp/390, Mbpp/433, Mbpp/433, Mbpp/433, Mbpp/433, Mbpp/433, Mbpp/433, Mbpp/433, Mbpp/465, Mbpp/471, Mbpp/471, Mbpp/471, Mbpp/471, Mbpp/550, Mbpp/550, Mbpp/550, Mbpp/550, Mbpp/550, Mbpp/550, Mbpp/566, Mbpp/592, Mbpp/592, Mbpp/619, Mbpp/619, Mbpp/619, Mbpp/619, Mbpp/634, Mbpp/644, Mbpp/644, Mbpp/651, Mbpp/651, Mbpp/651, Mbpp/651, Mbpp/678, Mbpp/678, Mbpp/687, Mbpp/715, Mbpp/715, Mbpp/715, Mbpp/715, Mbpp/719, Mbpp/719, Mbpp/719, Mbpp/719, Mbpp/719, Mbpp/72, Mbpp/722, Mbpp/722, Mbpp/722, Mbpp/722, Mbpp/722, Mbpp/722, Mbpp/748, Mbpp/748, Mbpp/748, Mbpp/748, Mbpp/748, Mbpp/748, Mbpp/748, Mbpp/782, Mbpp/792, Mbpp/792, Mbpp/81, Mbpp/81, Mbpp/81, Mbpp/81, Mbpp/81, Mbpp/81, Mbpp/81, Mbpp/827, Mbpp/827, Mbpp/850, Mbpp/850, Mbpp/855, Mbpp/868, Mbpp/876, Mbpp/883, Mbpp/883, Mbpp/888, Mbpp/888, Mbpp/888, Mbpp/888, Mbpp/907, Mbpp/907, Mbpp/945, Mbpp/95, Mbpp/960, Mbpp/960, Mbpp/960, Mbpp/960, Mbpp/960

## Suggested next steps

- Over-asking rate is 93.18% — the algorithm is questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering.
