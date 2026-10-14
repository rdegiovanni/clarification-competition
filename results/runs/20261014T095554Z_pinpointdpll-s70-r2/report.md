# Run report — LAASeR_PinpointDPLL (2026-10-14T09:58:31+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `3d665a5` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_pinpoint_dpll.py |
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
| **TDS** (ranking metric) | 0.6722 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.9000 | clarification quality — higher is better |
| Pass@1 | 70.00% | raw pass rate |
| Clarification rate | 100.00% | % tasks where ≥1 question was asked |
| Over-asking rate | 100.00% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.001376 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `3d665a5` at 2026-10-14T09:54:37+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.7002 | 0.6722 | ▼ -0.0280 |
| nDCG | 0.8286 | 0.9000 | ▲ +0.0714 |
| Pass@1 | 0.7286 | 0.7000 | ▼ -0.0286 |
| Clarification rate | 0.9857 | 1.0000 | ▲ +0.0143 |
| Over-asking rate | 0.9375 | 1.0000 | ▲ +0.0625 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| → | **LAASeR_PinpointDPLL (this run)** | us | openai/gpt-4.1-mini | **0.6722** |
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 23 | 39 | 58.97% |
| HumanEval | 26 | 31 | 83.87% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 14 |
| code ran but failed with an unhandled error | 6 |
| function name mismatch (NameError calling the entry point) | 1 |

## Failing task IDs

HumanEval/139, HumanEval/145, HumanEval/15, HumanEval/86, HumanEval/98, Mbpp/104, Mbpp/128, Mbpp/143, Mbpp/229, Mbpp/26, Mbpp/349, Mbpp/364, Mbpp/368, Mbpp/371, Mbpp/374, Mbpp/559, Mbpp/617, Mbpp/719, Mbpp/748, Mbpp/759, Mbpp/81

## Suggested next steps

- Over-asking rate is 100.00% — the algorithm is questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering.
- Mbpp pass rate (58.97%) is notably weaker than HumanEval (83.87%) — look at Mbpp failures first.
