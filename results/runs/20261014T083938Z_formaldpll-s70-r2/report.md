# Run report — LAASeR_FormalDPLL (2026-10-14T08:41:53+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `3d665a5` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_formal_dpll.py |
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
| **TDS** (ranking metric) | 0.5584 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.5286 | clarification quality — higher is better |
| Pass@1 | 57.14% | raw pass rate |
| Clarification rate | 58.57% | % tasks where ≥1 question was asked |
| Over-asking rate | 25.00% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.001126 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `3d665a5` at 2026-10-13T16:10:43+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.5144 | 0.5584 | ▲ +0.0440 |
| nDCG | 0.6429 | 0.5286 | ▼ -0.1143 |
| Pass@1 | 0.5286 | 0.5714 | ▲ +0.0428 |
| Clarification rate | 0.6571 | 0.5857 | ▼ -0.0714 |
| Over-asking rate | 0.5000 | 0.2500 | ▼ -0.2500 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| → | **LAASeR_FormalDPLL (this run)** | us | openai/gpt-4.1-mini | **0.5584** |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 20 | 39 | 51.28% |
| HumanEval | 20 | 31 | 64.52% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 23 |
| code ran but failed with an unhandled error | 7 |

## Failing task IDs

HumanEval/139, HumanEval/142, HumanEval/145, HumanEval/15, HumanEval/17, HumanEval/36, HumanEval/40, HumanEval/6, HumanEval/72, HumanEval/82, HumanEval/98, Mbpp/128, Mbpp/143, Mbpp/215, Mbpp/229, Mbpp/26, Mbpp/349, Mbpp/368, Mbpp/371, Mbpp/374, Mbpp/390, Mbpp/559, Mbpp/617, Mbpp/719, Mbpp/748, Mbpp/759, Mbpp/81, Mbpp/876, Mbpp/888, Mbpp/90

## Suggested next steps

- Over-asking rate is 25.00% — the algorithm is questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering.
