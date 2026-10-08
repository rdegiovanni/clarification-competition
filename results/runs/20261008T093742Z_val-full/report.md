# Run report — LAASeRAlgorithm (2026-10-08T11:10:59+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `c695a8c` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/LAASeRAlgorithm.py |
| Model | anthropic/claude-sonnet-5 |
| Temperature | 0.7 (SDK default) |
| Split / dataset | val (split:val) |
| Tasks evaluated | 770 |
| Unit tests (tests/) | PASSED |

## Unit tests

All offline regression tests passed (`tests/`, no network/Docker — these catch exception-handling bugs that the live benchmark may not trigger).

## Official competition metrics

Computed with `evaluate_responses.py`'s own `_compute_output_row` / `_turn_discounted_sucess` / `_normalized_discounted_cumulative_gain` — the same code a real leaderboard submission uses.

| Metric | Value | Meaning |
|---|---|---|
| **TDS** (ranking metric) | 0.7120 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.0701 | clarification quality — higher is better |
| Pass@1 | 71.56% | raw pass rate |
| Clarification rate | 16.75% | % tasks where ≥1 question was asked |
| Over-asking rate | 4.66% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.008123 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run

No earlier run recorded for this exact (algorithm, model, split, dataset) combination in `results/history.csv` — this is the first data point.

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `anthropic/claude-sonnet-5`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| → | **LAASeRAlgorithm (this run)** | us | anthropic/claude-sonnet-5 | **0.7120** |
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 287 | 420 | 68.33% |
| HumanEval | 264 | 350 | 75.43% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| no python code block returned | 218 |
| evalplus execution timeout | 1 |

## Failing task IDs

HumanEval/109, HumanEval/109, HumanEval/109, HumanEval/115, HumanEval/120, HumanEval/120, HumanEval/120, HumanEval/120, HumanEval/120, HumanEval/131, HumanEval/131, HumanEval/133, HumanEval/133, HumanEval/133, HumanEval/142, HumanEval/145, HumanEval/145, HumanEval/145, HumanEval/145, HumanEval/145, HumanEval/145, HumanEval/15, HumanEval/15, HumanEval/15, HumanEval/161, HumanEval/161, HumanEval/161, HumanEval/17, HumanEval/17, HumanEval/22, HumanEval/22, HumanEval/22, HumanEval/22, HumanEval/3, HumanEval/3, HumanEval/36, HumanEval/36, HumanEval/36, HumanEval/37, HumanEval/37, HumanEval/37, HumanEval/37, HumanEval/37, HumanEval/4, HumanEval/4, HumanEval/40, HumanEval/40, HumanEval/40, HumanEval/40, HumanEval/57, HumanEval/57, HumanEval/57, HumanEval/57, HumanEval/6, HumanEval/6, HumanEval/6, HumanEval/6, HumanEval/60, HumanEval/60, HumanEval/60, HumanEval/60, HumanEval/60, HumanEval/65, HumanEval/65, HumanEval/65, HumanEval/65, HumanEval/65, HumanEval/66, HumanEval/66, HumanEval/69, HumanEval/69, HumanEval/72, HumanEval/73, HumanEval/73, HumanEval/73, HumanEval/73, HumanEval/74, HumanEval/82, HumanEval/82, HumanEval/82, HumanEval/82, HumanEval/82, HumanEval/86, HumanEval/86, HumanEval/98, HumanEval/98, Mbpp/100, Mbpp/100, Mbpp/105, Mbpp/105, Mbpp/128, Mbpp/128, Mbpp/128, Mbpp/128, Mbpp/128, Mbpp/160, Mbpp/160, Mbpp/160, Mbpp/160, Mbpp/160, Mbpp/167, Mbpp/221, Mbpp/234, Mbpp/239, Mbpp/239, Mbpp/274, Mbpp/285, Mbpp/285, Mbpp/301, Mbpp/349, Mbpp/349, Mbpp/349, Mbpp/349, Mbpp/349, Mbpp/353, Mbpp/353, Mbpp/368, Mbpp/371, Mbpp/371, Mbpp/371, Mbpp/371, Mbpp/371, Mbpp/371, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/374, Mbpp/380, Mbpp/380, Mbpp/380, Mbpp/380, Mbpp/388, Mbpp/390, Mbpp/390, Mbpp/390, Mbpp/390, Mbpp/390, Mbpp/390, Mbpp/433, Mbpp/433, Mbpp/45, Mbpp/465, Mbpp/465, Mbpp/465, Mbpp/465, Mbpp/471, Mbpp/471, Mbpp/471, Mbpp/550, Mbpp/550, Mbpp/550, Mbpp/550, Mbpp/566, Mbpp/592, Mbpp/619, Mbpp/619, Mbpp/634, Mbpp/634, Mbpp/651, Mbpp/651, Mbpp/651, Mbpp/651, Mbpp/651, Mbpp/651, Mbpp/651, Mbpp/687, Mbpp/715, Mbpp/715, Mbpp/715, Mbpp/715, Mbpp/715, Mbpp/719, Mbpp/719, Mbpp/719, Mbpp/719, Mbpp/719, Mbpp/722, Mbpp/722, Mbpp/722, Mbpp/722, Mbpp/722, Mbpp/722, Mbpp/722, Mbpp/748, Mbpp/748, Mbpp/782, Mbpp/782, Mbpp/792, Mbpp/792, Mbpp/792, Mbpp/792, Mbpp/792, Mbpp/792, Mbpp/792, Mbpp/81, Mbpp/81, Mbpp/81, Mbpp/81, Mbpp/81, Mbpp/81, Mbpp/81, Mbpp/827, Mbpp/876, Mbpp/883, Mbpp/883, Mbpp/888, Mbpp/888, Mbpp/907, Mbpp/907, Mbpp/907, Mbpp/960, Mbpp/960, Mbpp/960, Mbpp/960, Mbpp/960, Mbpp/960

## Suggested next steps

- Over-asking rate is 4.66% — the algorithm is questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering.
- Only 41.86% of clarification questions were rated high-quality (score 3) — review question phrasing against the Criticality/Search-space/Leakage/Atomicity/Objectivity criteria in the README.
