# Run report — LAASeRAlgorithm (2026-10-08T08:46:42+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `4467c38` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/LAASeRAlgorithm.py |
| Model | anthropic/claude-sonnet-5 |
| Temperature | 0.7 (SDK default) |
| Split / dataset | demo (30 tasks) |
| Tasks evaluated | 30 |
| Unit tests (tests/) | PASSED |

## Unit tests

All offline regression tests passed (`tests/`, no network/Docker — these catch exception-handling bugs that the live benchmark may not trigger).

## Official competition metrics

Computed with `evaluate_responses.py`'s own `_compute_output_row` / `_turn_discounted_sucess` / `_normalized_discounted_cumulative_gain` — the same code a real leaderboard submission uses.

| Metric | Value | Meaning |
|---|---|---|
| **TDS** (ranking metric) | 0.8307 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.0333 | clarification quality — higher is better |
| Pass@1 | 83.33% | raw pass rate |
| Clarification rate | 16.67% | % tasks where ≥1 question was asked |
| Over-asking rate | 0.00% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.003198 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run

No earlier run recorded for this exact (algorithm, model, split, dataset) combination in `results/history.csv` — this is the first data point.

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `anthropic/claude-sonnet-5`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| → | **LAASeRAlgorithm (this run)** | us | anthropic/claude-sonnet-5 | **0.8307** |
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 25 | 30 | 83.33% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| no python code block returned | 5 |

## Failing task IDs

Mbpp/12, Mbpp/16, Mbpp/19, Mbpp/56, Mbpp/63

## Suggested next steps

- Only 20.00% of clarification questions were rated high-quality (score 3) — review question phrasing against the Criticality/Search-space/Leakage/Atomicity/Objectivity criteria in the README.
