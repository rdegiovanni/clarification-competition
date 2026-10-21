# Run report — GeneticSpecClarification (2026-10-20T14:58:07+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `99d19c9` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/genetic_spec_improvement.py |
| Model | openai/gpt-4.1-mini |
| Temperature | 0.7 |
| Split / dataset | demo (smoke(classes=Mbpp,HumanEval,n=70)) |
| Tasks evaluated | 70 |
| Unit tests (tests/) | PASSED |

## Unit tests

All offline regression tests passed (`tests/`, no network/Docker — these catch exception-handling bugs that the live benchmark may not trigger).

## Official competition metrics

Computed with `evaluate_responses.py`'s own `_compute_output_row` / `_turn_discounted_sucess` / `_normalized_discounted_cumulative_gain` — the same code a real leaderboard submission uses.

| Metric | Value | Meaning |
|---|---|---|
| **TDS** (ranking metric) | 0.5824 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.7286 | clarification quality — higher is better |
| Pass@1 | 60.00% | raw pass rate |
| Clarification rate | 84.29% | % tasks where ≥1 question was asked |
| Over-asking rate | 62.50% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.002274 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `99d19c9` at 2026-10-20T14:32:22+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.5961 | 0.5824 | ▼ -0.0137 |
| nDCG | 0.6714 | 0.7286 | ▲ +0.0572 |
| Pass@1 | 0.6143 | 0.6000 | ▼ -0.0143 |
| Clarification rate | 0.8286 | 0.8429 | ▲ +0.0143 |
| Over-asking rate | 0.6250 | 0.6250 | = +0.0000 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| → | **GeneticSpecClarification (this run)** | us | openai/gpt-4.1-mini | **0.5824** |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 19 | 39 | 48.72% |
| HumanEval | 23 | 31 | 74.19% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 16 |
| code ran but failed with an unhandled error | 12 |

## Failing task IDs

HumanEval/139, HumanEval/145, HumanEval/15, HumanEval/40, HumanEval/6, HumanEval/72, HumanEval/86, HumanEval/98, Mbpp/128, Mbpp/143, Mbpp/215, Mbpp/229, Mbpp/26, Mbpp/349, Mbpp/371, Mbpp/374, Mbpp/388, Mbpp/390, Mbpp/559, Mbpp/617, Mbpp/619, Mbpp/719, Mbpp/748, Mbpp/759, Mbpp/782, Mbpp/81, Mbpp/868, Mbpp/876

## Suggested next steps

- Over-asking rate is 62.50% — the algorithm is questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering.
- Mbpp pass rate (48.72%) is notably weaker than HumanEval (74.19%) — look at Mbpp failures first.
