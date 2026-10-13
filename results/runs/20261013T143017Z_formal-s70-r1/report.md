# Run report — LAASeR_Formal (2026-10-13T14:32:31+00:00)

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
| **TDS** (ranking metric) | 0.4692 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.0714 | clarification quality — higher is better |
| Pass@1 | 47.14% | raw pass rate |
| Clarification rate | 7.14% | % tasks where ≥1 question was asked |
| Over-asking rate | 0.00% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.000895 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run

No earlier run recorded for this exact (algorithm, model, split, dataset) combination in `results/history.csv` — this is the first data point.

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |
| → | **LAASeR_Formal (this run)** | us | openai/gpt-4.1-mini | **0.4692** |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 17 | 39 | 43.59% |
| HumanEval | 16 | 31 | 51.61% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 27 |
| code ran but failed with an unhandled error | 10 |

## Failing task IDs

HumanEval/115, HumanEval/117, HumanEval/120, HumanEval/139, HumanEval/142, HumanEval/145, HumanEval/15, HumanEval/161, HumanEval/17, HumanEval/36, HumanEval/40, HumanEval/65, HumanEval/82, HumanEval/86, HumanEval/98, Mbpp/100, Mbpp/128, Mbpp/143, Mbpp/215, Mbpp/229, Mbpp/26, Mbpp/349, Mbpp/368, Mbpp/371, Mbpp/374, Mbpp/390, Mbpp/559, Mbpp/617, Mbpp/619, Mbpp/651, Mbpp/719, Mbpp/748, Mbpp/759, Mbpp/792, Mbpp/81, Mbpp/876, Mbpp/888

## Suggested next steps

- No obvious red flag from this single run; compare the TDS trend across multiple runs in `results/history.csv` before concluding anything changed.
