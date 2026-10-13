# Run report — LAASeR_PinpointSig (2026-10-13T13:56:55+00:00)

## Metadata

| Field | Value |
|---|---|
| Commit | `8f56154` (dirty — uncommitted changes) |
| Algorithm file | clarify/algorithms/laaser_pinpoint_sig.py |
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
| **TDS** (ranking metric) | 0.6447 | turn-discounted success — higher is better |
| **nDCG** (tie-break) | 0.7429 | clarification quality — higher is better |
| Pass@1 | 67.14% | raw pass rate |
| Clarification rate | 100.00% | % tasks where ≥1 question was asked |
| Over-asking rate | 100.00% | % well-specified tasks needlessly questioned |
| Avg. cost / task | $0.001109 | prompt cost only, reported, no rank effect |

> Sampling temperature is 0.7 (non-zero), so re-running on the exact same commit/dataset will still shift these numbers by a point or two — treat small deltas below as noise, not signal. Only trust a difference that holds up across more than one run.

## Vs. previous run (same algorithm/model/split/dataset)

Previous: commit `8f56154` at 2026-10-13T13:54:04+00:00

| Metric | Previous | Now | Δ |
|---|---|---|---|
| TDS | 0.6173 | 0.6447 | ▲ +0.0274 |
| nDCG | 0.7000 | 0.7429 | ▲ +0.0429 |
| Pass@1 | 0.6429 | 0.6714 | ▲ +0.0285 |
| Clarification rate | 1.0000 | 1.0000 | = +0.0000 |
| Over-asking rate | 1.0000 | 1.0000 | = +0.0000 |

## Public leaderboard position (informational only)

`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. This run used `openai/gpt-4.1-mini`, so ranking against it is **not an apples-to-apples comparison** — use it as a rough compass, not a verdict.

| Rank | Algorithm | Team | Model | TDS |
|---|---|---|---|---|
| → | **LAASeR_PinpointSig (this run)** | us | openai/gpt-4.1-mini | **0.6447** |
| 1 | GatedClarification | STIL-ETS | openai/gpt-4.1-mini | 0.6410 |
| 2 | ContractFirstClarifier | D4vidHuang | openai/gpt-4.1-mini | 0.5973 |
| 3 | Okanagan | baseline | openai/gpt-4.1-mini | 0.5917 |
| 4 | ClarifyGPT | baseline | openai/gpt-4.1-mini | 0.5625 |
| 5 | LLMClarification | baseline | openai/gpt-4.1-mini | 0.4974 |

## Breakdown by benchmark (lowest pass-rate first — fix these first)

| Benchmark | Passed | Total | Pass rate |
|---|---|---|---|
| Mbpp | 21 | 39 | 53.85% |
| HumanEval | 26 | 31 | 83.87% |

## Failure reasons (priority order)

| Reason | Count |
|---|---|
| code ran but produced the wrong output | 18 |
| code ran but failed with an unhandled error | 5 |

## Failing task IDs

HumanEval/139, HumanEval/145, HumanEval/15, HumanEval/65, HumanEval/98, Mbpp/100, Mbpp/143, Mbpp/229, Mbpp/26, Mbpp/349, Mbpp/368, Mbpp/371, Mbpp/374, Mbpp/390, Mbpp/559, Mbpp/592, Mbpp/617, Mbpp/651, Mbpp/719, Mbpp/748, Mbpp/759, Mbpp/81, Mbpp/888

## Suggested next steps

- Over-asking rate is 100.00% — the algorithm is questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering.
- Mbpp pass rate (53.85%) is notably weaker than HumanEval (83.87%) — look at Mbpp failures first.
