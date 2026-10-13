# Run report — LAASeR_Formal (2026-10-13T14:44:50+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `bdcc26b` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_formal.py |
| Model | openai/gpt-4.1-mini |
| Temperature | 0.7 (SDK default) |
| Split / dataset | demo (smoke(source=val,classes=Mbpp,HumanEval,n=70)) |
| Tasks evaluated | 70 |
| Unit tests (tests/) | PASSED |

## Unit tests

All offline regression tests passed (`tests/`, no network/Docker — these catch exception-handling bugs that the live benchmark may not trigger).

## Official competition metrics

Computed with `evaluate_responses.py`'s own `_compute_output_row` / `_turn_discounted_sucess` / `_normalized_discounted_cumulative_gain` — the same code a real leaderboard submission uses.

| Metric | Value | Meaning |
|---|---|---|
| **TDS** (ranking metric) | 0.6453 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.9143 | clarification quality — higher is better |
| Pass@1 | 67.14% | raw pass rate |
| Clarification rate | 98.57% | % tasks where ≥1 question was asked |
| Over-asking rate | 93.75% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.000856 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `bdcc26b` at 2026-10-13T14:42:07+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.6184 | 0.6453 | ▲ +0.0269 |
| nDCG | 0.9143 | 0.9143 | = +0.0000 |
| Pass@1 | 0.6429 | 0.6714 | ▲ +0.0285 |
| Clarification rate | 0.9714 | 0.9857 | ▲ +0.0143 |
| Over-asking rate | 0.8750 | 0.9375 | ▲ +0.0625 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| → | **LAASeR_Formal (this run)** | us | openai/gpt-4.1-mini | **0.6453** |
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
| code ran but produced the wrong output | 13 |
| code ran but failed with an unhandled error | 9 |
| function name mismatch (NameError calling the entry point) | 1 |

## Failing task IDs

HumanEval/139, HumanEval/142, HumanEval/145, HumanEval/15, HumanEval/6, HumanEval/86, HumanEval/98, Mbpp/104, Mbpp/128, Mbpp/143, Mbpp/229, Mbpp/26, Mbpp/368, Mbpp/371, Mbpp/374, Mbpp/390, Mbpp/559, Mbpp/617, Mbpp/719, Mbpp/748, Mbpp/759, Mbpp/81, Mbpp/888

## Suggested next steps

- Over-asking rate is 93.75% — the algorithm is questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering.
- Mbpp pass rate (58.97%) is notably weaker than HumanEval (77.42%) — look at Mbpp failures first.
