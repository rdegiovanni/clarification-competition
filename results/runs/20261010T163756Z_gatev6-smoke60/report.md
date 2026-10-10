# Run report — LAASeR_GateV6 (2026-10-10T16:45:10+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `aec12a4` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_gate_v6.py |
| Model | openai/gpt-4.1-mini |
| Temperature | 0.7 (SDK default) |
| Split / dataset | demo (smoke(classes=Mbpp,HumanEval,n=60)) |
| Tasks evaluated | 60 |
| Unit tests (tests/) | PASSED |

## Unit tests

All offline regression tests passed (`tests/`, no network/Docker — these catch exception-handling bugs that the live benchmark may not trigger).

## Official competition metrics

Computed with `evaluate_responses.py`'s own `_compute_output_row` / `_turn_discounted_sucess` / `_normalized_discounted_cumulative_gain` — the same code a real leaderboard submission uses.

| Metric | Value | Meaning |
|---|---|---|
| **TDS** (ranking metric) | 0.7288 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.6167 | clarification quality — higher is better |
| Pass@1 | 75.00% | raw pass rate |
| Clarification rate | 68.33% | % tasks where ≥1 question was asked |
| Over-asking rate | 100.00% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.004231 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run

No earlier run recorded for this exact (algorithm, model, split, dataset) combination in `results/history.csv` — this is the first data point.

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| → | **LAASeR_GateV6 (this run)** | us | openai/gpt-4.1-mini | **0.7288** |
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 17 | 30 | 56.67% |
| HumanEval | 28 | 30 | 93.33% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but failed with an unhandled error | 8 |
| code ran but produced the wrong output | 7 |

## Failing task IDs

HumanEval/139, HumanEval/91, Mbpp/229, Mbpp/239, Mbpp/26, Mbpp/31, Mbpp/33, Mbpp/433, Mbpp/559, Mbpp/575, Mbpp/617, Mbpp/655, Mbpp/719, Mbpp/755, Mbpp/90

## Suggested next steps

- Over-asking rate is 100.00% — the algorithm is questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering.
- Mbpp pass rate (56.67%) is notably weaker than HumanEval (93.33%) — look at Mbpp failures first.
