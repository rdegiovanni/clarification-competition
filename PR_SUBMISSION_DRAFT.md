Title: Submission: LAASeRAlgorithm (LAASeR - LIST)

---

## Submission type

- [x] **New submission** — adds `clarify/algorithms/<name>.py`
- [ ] **Update of an existing submission** — replaces our earlier file
- [ ] **Leaderboard update only** — adds/updates our row in `docs/data/leaderboard.csv` (`confirmed=false`)

## Team

| | |
| --- | --- |
| **Team name** | LAASeR - LIST |
| **Team members** | Matias Brizzio (LIST), Jordi Cabot (LIST), Renzo Degiovanni (LIST) |
| **Main contact** | Matias Brizzio, matias.brizzio@list.lu |
| **License** | MIT |

## Algorithm

**File:** `clarify/algorithms/LAASeRAlgorithm.py`
**Class name:** `LAASeRAlgorithm`

**Summary** (2–5 sentences: what does the algorithm do, when does it ask, how does it decide?)

The algorithm sends the task prompt and entry point to the model with instructions to either
output `READY_TO_CODE` followed by a Python code block, or ask one `QUESTION: ...` if the
description is missing crucial details. If a question is asked, the human's answer is appended to
the prompt as a labeled clarification turn and the model is asked again, repeating until the model
is ready to code or a turn/budget limit is reached. The prompt explicitly tells the model it is
competing in a clarification challenge, where unnecessary questions are penalized, to discourage
over-asking.

**Core mechanism** (optional, a bit more detail: pipeline stages, prompts, how `env.llm`, `env.ask_human`, and `env.exec_code` are used, stopping criteria)

Single loop: build a prompt from the task description plus any accumulated clarification
question/answer pairs, call `env.llm(messages)`, and branch on the response. `READY_TO_CODE` ->
parse and return the code block as the final candidate. `QUESTION: ...` -> call
`env.ask_human(clarifying_question)`, append the Q/A pair to the clarification history, and loop
again. Any other response, or a `TooManyQuestionException`/`LimitsExceededException` raised by the
SDK (clarification-turn or budget limit reached), returns the best candidate produced so far
(empty string if none). `env.exec_code` is not used by this algorithm.

**Related work / inspiration** (optional: papers, existing systems)

<!-- n/a -->

## Algorithm parameters and defaults

List every key of `DEFAULT_CONFIG` (everything read from `self.config`). The defaults below are the configuration that will be evaluated.

`LAASeRAlgorithm` does not define a `DEFAULT_CONFIG` and does not read from `self.config` — it has
no configurable parameters.

- [x] N/A — no `DEFAULT_CONFIG`/`self.config` usage in this file.
- [x] No parameter is read from environment variables, files, or hard-coded elsewhere.

## OPTIONAL - Evaluation settings used for the reported results

Exact `generate_responses.py` options used to produce the numbers below (fill in even if you used the defaults).

| Option | Value |
| --- | --- |
| `--language_model` | `openai/gpt-4.1-mini` |
| `--temperature` | `0.7` |
| `--clarification_model` | *(default)* |
| `--max_clarification_turns` | `1` |
| `--max_prompt_budget` | `1.0` |
| `--max_clarification_budget` | `1.0` |
| `--num_samples` | `1` |
| `--split` | `val` |
| Other options / algorithm overrides | *(none)* |

**Exact commands run:**

```bash
python generate_responses.py clarify/algorithms/LAASeRAlgorithm.py --split val \
  --language_model openai/gpt-4.1-mini --output_path generate.jsonl
python evaluate_responses.py --split val --generation_path generate.jsonl \
  --output_path results.jsonl --force_rerun
```

## OPTIONAL - Validation results

Results of `evaluate_responses.py` on the public validation split (770 tasks).

| TDS | nDCG | Pass@1 | Clarification rate | Over-asking rate | Avg. cost / task (USD) |
| --- | --- | --- | --- | --- | --- |
| 0.5693 | 0.2117 | 57.53% | 25.45% | 10.36% | 0.000351 |

**Generation / result files:** TODO — upload `generate.jsonl` / `results.jsonl` from
`results/runs/20261009T143632Z_LAASeRAlgorithm/` to an external host (release asset / Zenodo /
gist) before the final submission deadline; not committed to the repository.

## Leaderboard

- [x] No leaderboard change in this pull request (organizers will add a confirmed row after reproduction), **or**
- [ ] `docs/data/leaderboard.csv` contains exactly one added/updated row for our algorithm, generated with `evaluate_responses.py ... --submit "<Team name>"`, with `confirmed=false`
- [ ] No other rows (baselines, other teams) and no header were modified
- [ ] The `model` column matches `--language_model` above

## Submission checklist

- [x] The pull request adds/changes only `clarify/algorithms/LAASeRAlgorithm.py` (and optionally our leaderboard row)
- [x] The file starts with the SPDX header and the docstring contains `Team`, `Team Members`, and `Main Contact`
- [x] Exactly one public class inherits from `ClarificationAlgorithmBase`; prototypes are prefixed with `_`
- [x] All LLM calls, clarifications, and code execution go through `env.llm`, `env.ask_human` / `env.can_ask`, and `env.exec_code`
- [x] Only the standard library and packages already in `pyproject.toml` are imported; `pyproject.toml` and `uv.lock` are unchanged (additional libraries were requested via a *Library request* issue: n/a)
- [x] No model name is hard-coded; the algorithm runs with the default environment settings
- [x] `python generate_responses.py clarify/algorithms/LAASeRAlgorithm.py --split val` runs without errors on a fresh `uv sync`
- [x] We developed on the released splits only and did not tune on validation instances
- [x] We have read CONTRIBUTING.md and agree to the competition rules

## Notes for the organizers (optional)

This is a draft registration PR ahead of the registration deadline. The algorithm file and
validation numbers above are final; the generation/result file hosting link is still pending and
will be added before the submission deadline. Results come from one run on `openai/gpt-4.1-mini`,
`temperature=0.7` (the default); repeated runs at this temperature vary by a few points of TDS
from sampling noise alone.
