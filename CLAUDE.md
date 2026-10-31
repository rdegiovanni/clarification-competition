# CLAUDE.md — Clarification Competition (team LAASeR)

This file is the single source of truth for setup, running, testing, and tracking progress on
our submission. Working rule for this repo: **no change to `clarify/algorithms/LAASeRAlgorithm.py`
is accepted without a measurement from `scripts/evaluate.sh` showing its effect, before vs. after.**

## What this repo is

The Clarification Challenge (ICSE 2027 competition track, University of Luxembourg + Michigan
Tech). An LLM coding assistant is given an underspecified function-writing task from MBPP/HumanEval
and must decide whether to ask a clarifying question before writing code. Our submission is one
file: `clarify/algorithms/LAASeRAlgorithm.py` (authored by Renzo Degiovanni, commits `6223252` and
`4467c38`). It implements `ClarificationAlgorithmBase.run(self, env, problem) -> str`, loops calling
`env.llm(messages)` until the model says `READY_TO_CODE` (returns code) or `QUESTION: ...` (asks
`env.ask_human(...)` and loops again), bounded by turn/budget limits enforced by the SDK.

Full rules/API: `README.md`. Submission process/dates: `CONTRIBUTING.md`.

## Scoring, in one paragraph

Primary rank metric is **TDS** (turn-discounted success — a pass with 0 clarification turns
scores 1.0, each extra turn discounts it by `log(10)/log(10+turns)`). **nDCG** is the tie-breaker
only, scored by an LLM judge on clarification quality (Criticality / Search space / Leakage /
Atomicity / Objectivity). Also reported, no rank effect: Pass@1, clarification rate, over-asking
rate (clarifying on a task that didn't need it — actively bad), avg cost/task. Current public
leaderboard (`docs/data/leaderboard.csv`, all on `openai/gpt-4.1-mini`):

| Algorithm | TDS | nDCG | Team |
|---|---|---|---|
| GatedClarification | 0.6410 | 0.8987 | STIL-ETS (current leader) |
| ContractFirstClarifier | 0.5973 | 0.8247 | D4vidHuang |
| Okanagan (baseline) | 0.5917 | 0.7688 | — |
| ClarifyGPT (baseline) | 0.5625 | 0.3818 | — |
| LLMClarification (baseline) | 0.4974 | 0.0000 | — |

Our goal is to beat 0.6410 TDS (then 0.8987 nDCG as tie-break) **on the same model used for
scoring** (the private test set uses a fixed model per `docs/data/competition.json`'s FAQ — the
leaderboard entries above all used `openai/gpt-4.1-mini`; our dev runs default to
`anthropic/claude-sonnet-5`, see caveat below).

**Important caveat for every report you read:** our own runs are not directly comparable to the
public leaderboard rows unless we use the same model. They're a compass, not a verdict. Also,
default `temperature=0.7` means repeated runs on the same code/data differ by a few points of TDS
from sampling noise alone — a single run is not proof of a regression or improvement; look at the
trend in `results/history.csv` across multiple runs before concluding anything.

## Setup

```bash
uv sync --all-extras --dev        # installs deps into .venv via uv (Python 3.13, managed by uv)
```

Docker is required for the sandboxed `evalplus` execution (`ganler/evalplus` image, pulled
automatically on first use) — make sure Docker Desktop is running before `evaluate_responses.py`
or `scripts/evaluate.sh`.

### LLM credentials (never commit the literal secret)

This repo talks to LiteLLM, which reads provider credentials from standard env vars
(`ANTHROPIC_API_KEY`, `ANTHROPIC_API_BASE`) — see `clarify/llm.py`, no key is ever passed in code.
Our access is through a private corporate Anthropic gateway, configured in `~/.zshrc` as
`ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL`. A git-ignored `.env` file at the repo root maps
those to the names litellm expects, **by reference only** (not the literal value):

```
ANTHROPIC_API_KEY=$ANTHROPIC_AUTH_TOKEN
ANTHROPIC_API_BASE=$ANTHROPIC_BASE_URL
```

`.env` is listed in `.gitignore` (confirmed via `git check-ignore -v .env`) and `scripts/evaluate.sh`
sources it automatically (`set -a && source .env && set +a`) before running anything. If you open a
fresh shell and need to run `generate_responses.py`/`evaluate_responses.py` directly (not through
`scripts/evaluate.sh`), source `.env` yourself first, or export `ANTHROPIC_API_KEY`/`ANTHROPIC_API_BASE`
from your own shell profile. **Never paste the literal token value into any file tracked by git,
chat output, or logs.**

## Running everything (one command)

```bash
scripts/evaluate.sh
```

This is the script the user asked for: it runs the offline unit tests, generates responses, scores
them with the competition's own metric code, and writes a Markdown report — all in one shot. It:

1. Runs `uv run python -m unittest discover -s tests -v` (offline, no network/Docker) and saves the
   log — this is where the **unit test results** live (previously these only printed to console and
   disappeared; now every run saves them to `results/runs/<run>/unittest.log`).
2. Runs `generate_responses.py` against the chosen dataset/split with the chosen algorithm+model.
3. Runs `evaluate_responses.py --force_rerun` (official Docker-sandboxed scoring: TDS, nDCG,
   Pass@1, clarification rate, over-asking rate, avg cost).
4. Runs `scripts/make_report.py`, which imports `_compute_output_row` /
   `_turn_discounted_sucess` / `_normalized_discounted_cumulative_gain` directly from
   `evaluate_responses.py` (not a reimplementation — guaranteed to match the real scoring),
   appends one row to `results/history.csv`, and writes a Markdown report.

Output per run, under `results/runs/<timestamp>_<label>/`:
- `unittest.log`, `generate.log`, `evaluate.log` — full raw logs (including the per-task rich
  tables `evaluate_responses.py` prints — these are what "disappeared" before; now saved to disk).
- `generate.jsonl`, `results.jsonl` — raw structured output per task.
- `report.md` — the human-readable summary (metrics, vs.-previous-run delta, vs.-leaderboard
  position, pass-rate by benchmark, failure-reason breakdown, failing task IDs, suggested next
  steps). Also copied to `results/latest_report.md` for quick access.
- A new row in `results/history.csv` (one row per run, keyed by algorithm/model/split/dataset) —
  this is the actual "coverage" tracking the user asked for: our position over time on the
  competition's own metrics, not code coverage.

Common invocations:

```bash
scripts/evaluate.sh                                   # demo set (30 tasks), default algorithm+model
scripts/evaluate.sh --split val                        # official validation split (770 tasks)
scripts/evaluate.sh --language-model openai/gpt-4.1-mini  # match the public leaderboard's model exactly
scripts/evaluate.sh --clarify-py path/to/variant.py --label my-variant
scripts/evaluate.sh --max-workers 8
```

Run `scripts/evaluate.sh --help` for the full flag list.

## Running pieces individually

```bash
# offline unit tests only
uv run python -m unittest discover -s tests -v

# generation only
uv run python generate_responses.py clarify/algorithms/LAASeRAlgorithm.py \
  --output_path results/manual_gen.jsonl --language_model anthropic/claude-sonnet-5

# evaluation only (reuses an existing generation file)
uv run python evaluate_responses.py --generation_path results/manual_gen.jsonl \
  --output_path results/manual_results.jsonl --force_rerun

# repo/submission validation (same checks CI runs)
uv run python scripts/validate_repository.py
uvx ruff check .
uvx ruff format --check .
```

## Competition rules that constrain how we work here

- Submission = **one file**, `clarify/algorithms/<name>.py`, with an SPDX header + docstring
  (Team/Team Members/Main Contact). We must **not** modify `pyproject.toml`, `uv.lock`, or other
  files under `clarify/` as part of the submission PR. (`tests/`, `scripts/`, `results/` are dev
  tooling outside `clarify/` and are fine to add/change.)
- SDK bug fixes are welcome but must be a **separate PR** from the algorithm submission.
  Eval-script/metric changes (`evaluate_responses.py`, `generate_responses.py`) are organizer-only.
- Algorithm interacts with the benchmark **only** through the SDK (`env.llm`, `env.ask_human`,
  `env.exec_code`) — no reading hidden tests, no reaching into private state.
- Anti-cheat (`scripts/validate_repository.py`) statically rejects any `_`-prefixed
  attribute/key/env access anywhere in `clarify/algorithms/`. `ClarificationEnvironment` also
  blocks this at runtime. Keep this in mind before adding any helper that pokes at `env` internals.
- Defaults we evaluate under unless told otherwise (`CONTRIBUTING.md`): `--language_model
  openai/gpt-4.1-mini`, `--temperature 0.7`, `--max_clarification_turns 1`,
  `--max_prompt_budget`/`--max_clarification_budget` 1.0 USD each. Our dev default model is
  `anthropic/claude-sonnet-5` (gateway access) — switch to `openai/gpt-4.1-mini` before comparing
  directly against the public leaderboard.
- One submission per team; never pass `--trusted` when self-submitting to the leaderboard.

## Known SDK quirks (not ours to fix, documented so we don't "rediscover" them)

- `evaluate_responses.py`'s `print_statistics()` (console-only) computes over-asking rate with
  `r.get("need_clarification", True)` as the default, while `_compute_output_row()` (the function
  that actually produces leaderboard numbers) defaults it to `False`. Only matters for results
  missing a `need_clarification` key; harmless for normal runs but can make the console table and
  the real score disagree slightly. Eval-script changes are organizer-only, so we just document it.
- **A single huge-int task (e.g. `HumanEval/139`, `special_factorial`) can crash an entire
  `evaluate_responses.py` batch, discarding every other task's result, unless
  `PYTHONINTMAXSTRDIGITS=0` is exported in the shell before launching it.** CPython 3.11+'s
  int-to-str conversion digit limit (4300 by default) gets tripped by `clarify/runtime.py`'s
  `_construct_tests` calling `str(value)` on a factorial-sized ground-truth value — this happens
  *host-side*, inside a `ProcessPoolExecutor` worker, before Docker is even involved, and the
  exception is unhandled there, killing the whole run. Setting the env var on the host avoids that
  crash; it does **not** fix the task itself, since the Docker sandbox container runs its own
  fresh interpreter that doesn't inherit host env either way — that task still fails cleanly on
  its own, which is the correct/expected per-task outcome. Full writeup, including a reproduced
  before/after: `docs/failure-analysis.md`'s `HumanEval/139` entry. Always run our own
  `scripts/evaluate.sh` invocations as `PYTHONINTMAXSTRDIGITS=0 scripts/evaluate.sh ...`.

## Decision log

Every entry: what changed, why, which script/run measured it, before → after.

### 2026-10-08 — First `scripts/evaluate.sh` run (anchors the baseline)

- **What**: ran the finished one-command pipeline for the first time, on commit `4467c38` (dirty —
  the exception-handling fix below was applied but not yet committed), demo set,
  `anthropic/claude-sonnet-5`.
- **Result**: TDS 0.8307, nDCG 0.0333, Pass@1 83.33%, clarification rate 16.67%, over-asking 0.00%,
  avg cost $0.003198/task. Full report: `results/runs/20261008T084523Z_LAASeRAlgorithm/report.md`.
  Row logged in `results/history.csv`.
- **Reading it**: nDCG (0.0333) is far below every leaderboard row — only 1 of 5 clarification
  questions asked (20%) was rated high-quality (score 3). 5/30 failures all share one failure
  signature ("no python code block returned", tasks `Mbpp/12, 16, 19, 56, 63`) — worth inspecting
  those raw model responses before anything else, since it's a single failure mode hitting 1/6 of
  the demo set. This is the baseline every future change should be measured against (same
  model/split/dataset) until we switch dev default to `openai/gpt-4.1-mini` for leaderboard parity.

### 2026-10-08 — Fix `except (A | B):` in `LAASeRAlgorithm.py`

- **What**: `except (TooManyQuestionException | LimitsExceededException):` used Python's `|`
  type-union operator, which is invalid inside an `except` clause — raises `TypeError: catching
  classes that do not inherit from BaseException is not allowed` whenever either exception is
  actually raised (i.e. whenever the clarification-turn or budget limit is hit). Changed to tuple
  syntax: `except (TooManyQuestionException, LimitsExceededException):`.
- **Why**: confirmed with a standalone repro (`except (A | B):` raises `TypeError` even when `A`/`B`
  are plain exception classes and the raised exception matches one of them) and with a new offline
  regression test, `tests/test_laaser_algorithm.py` — 2 of 3 cases failed with exactly that
  `TypeError` before the fix, all 3 passed after.
- **How measured**: `uv run python -m unittest discover -s tests -v` (red → green). This is an
  offline, no-network/no-Docker test specifically because the bug only triggers when a turn/budget
  limit is hit, which the 30-task demo set does not reliably exercise — a benchmark run alone would
  not have caught this reliably.
- **Benchmark before/after** (30-task demo set, `anthropic/claude-sonnet-5`, `temperature=0.7`):
  TDS 0.8947 → 0.8280, Pass@1 90.00% → 83.33%. **This drop is not attributable to the fix** — we
  confirmed `grep -c "EXCEPTION" results/baseline_demo_gen.jsonl` returns 0 in both runs (the bug's
  failure path never actually triggered in either run; no task hit the turn/budget limit), so the
  delta is sampling noise from `temperature=0.7`, not a regression. The fix is still correct and
  worth keeping — it prevents an unhandled crash whenever a future run *does* hit a budget/turn
  limit — but don't read the TDS delta above as evidence either way. Judge future changes by trends
  across several `scripts/evaluate.sh` runs, not a single before/after pair.

<!-- Add new entries above this line, newest first. -->

### 2026-10-15 — v7 (`laaser_pinpoint_smt_3.py`) failure analysis

- **What**: smoke-70 (val, seed 42, `openai/gpt-4.1-mini`), defaults vs.
  `--question_samples 1 --candidates 1`, one run each.
- **Result**: TDS 0.6739 (49/70) vs. 0.6327 (46/70); with the two earlier default runs (51, 45)
  the spread on identical code is 6 tasks, so the difference is within noise.
- **Reading it**: the 21 failures of the default run all asked and got QUALITY=3 answers; they
  are extra undeclared test arguments, forced hard tasks, or a hidden requirement other than
  the one asked. Over-asking (87.5%) costs ~0.008 TDS. The z3 layers run only when the audit
  codes, i.e. in ~3 of 70 tasks. Full write-up: `docs/v7-failure-analysis.md`.

### 2026-10-20 — smt_3: voting, spec rewrite, defect resolver (all off by default)

- **Determinism** (22 flaky smoke tasks, `results/flaky_sets/`, 2 runs each): v7 defaults 8
  tasks flip, 15/15 passed; `--decision_votes 5 --question_choice consensus --candidates 5`
  4 flip, 14/16 passed, cost $0.0042 → $0.0065/task.
- **Combo** on smoke-70 (`combo-resolve-r1`: voting + consensus + `spec_rewrite` +
  `resolve_defects`): TDS 0.6464 (47/70) vs. v7 0.6739 (49/70), $0.0082/task. Tasks with 2
  hidden requirements 7 → 9 of 13, with 1 requirement 22 → 19 of 23. `consensus` picked bundled
  questions (QUALITY=1 answers 5 → 8, nDCG 0.886 → 0.843); the judge filters them.
- **Hidden requirements per task vs. pass** (v7): 1 requirement 22/23, 2+: 10/24 — the ceiling
  of one clarification turn.

### 2026-10-21 — v7 on the full validation split: TDS 0.7108

- **What**: `laaser_pinpoint_smt_3.py` with its defaults, `--split val`, `openai/gpt-4.1-mini`
  (run `20261021T141943Z_v7-val-r1`), vs. Pinpoint's three val runs.
- **Result**: TDS 0.7108, 567/768 passed, nDCG 0.870, $0.0036/task; Pinpoint 0.6834 / 0.7021 /
  0.7083 (545 / 561 / 566 passed), $0.0010/task. MBPP +16 over Pinpoint's mean, HumanEval -6.
- **Reading it**: above 0.70 but one run, barely above Pinpoint's best; repeat before concluding.
  26% of v7's failures are signatures (27 extra arguments, 25 argument order/type in 9 MBPP
  tasks). On smoke-70, `decision_votes`, `resolve_defects` and `question_target=divergence`
  did not raise the pass count (details: `docs/v7-failure-analysis.md`, update of 2026-10-21).

### 2026-10-21 — GeneticSpecClarification on smoke-70: TDS 0.5955

- **What**: `genetic_spec_improvement.py` (commit `9ebf797`) on smoke-70 (val, seed 42).
- **Result**: TDS 0.5955, 43/70, nDCG 0.671, $0.0022/task vs. v7 0.62-0.70 (45-51 passed).
- **Reading it**: its questions are bundled or ask for test cases (QUALITY=1 answers 12 vs. 5-6);
  it loses mostly on 1-requirement tasks. Table in `docs/v7-failure-analysis.md`.
- **Follow-up** (`genetic_spec_improvement_v7q.py`, the original file is unchanged): with v7's
  question rules and an entry-point alias (the code sometimes
  named the function `candidate`): 39 then 41/70, nDCG 0.786 / 0.743; still below v7's worst run.

### 2026-10-23 — failure origins; convention resolver, question priority, no-z3

- **Failure origins** (v7, val, `scripts/classify_failures.py`): wrong value 61%, argument
  order/type 13%, wrong type 8.5%, extra arguments 8.5%, missing arguments 5%; 68% of failures
  are tasks with 2+ hidden requirements. MBPP 69.3%, HumanEval 79.4%.
- **Measured, no gain** (flags off by default): `resolve_mode=convention` 8, 11/23 on the
  multi-requirement subset (v7 13, 10, 10); `question_priority` 47/70 with nDCG 0.800;
  `use_solver=False` 45/70 (v7 45-51; the losses did not involve z3). v7 does not need z3.
- Public leader (site): ZarutskiyClarifier TDS 0.6697. Deadline Nov 6. Details:
  `docs/v7-failure-analysis.md`, update of 2026-10-23.

### 2026-10-23 — second v7 val run: TDS 0.6906; v7 and Pinpoint tied overall

- **Result**: v7 val runs 0.7108 and 0.6906 (mean 0.7007, sd 0.014) vs. Pinpoint 0.6834 /
  0.7021 / 0.7083 (mean 0.6979); 101/768 tasks flip between the two v7 runs. All above the
  leader's 0.6697.
- **Reading it**: tied overall at 3.5x the cost, but consistently split by benchmark: v7 +14 on
  MBPP, -11.5 on HumanEval. Next: Pinpoint's behaviour when the prompt shows a `def` signature,
  v7 otherwise (`docs/v7-failure-analysis.md`).

### 2026-10-24 — argument order: data structure first (offline what-if)

- **No gain**: `stub_profile="pinpoint"` 277/350 on val HumanEval (Pinpoint 282-286, v7 278/267);
  `argument_convention` (a coding rule) 266 vs. 270/267 on val MBPP: the model ignores the rule.
- **Finding**: passing code puts the collection first in 31/33 two-parameter functions. Swapping
  (scalar, collection) parameters in the code of `v7-val-r2`, scored offline with the official
  tests: the 9 touched variants 1/9 → 5/9 (Mbpp/433 0/6 → 5/6; Mbpp/128 broken where the answer
  fixed the order). Threats to validity (ad hoc, three task ids, small prior sample) in
  `docs/v7-failure-analysis.md`, update of 2026-10-24.
- **In the algorithm**: `reorder_arguments` (off by default, guarded by the answer); smoke-70
  50/70, nothing lost. Asking about the order instead: 98 such MBPP questions pass at 69%, the average.

### 2026-10-25 — v7 + reorder_arguments on val: TDS 0.7033, MBPP 293

- MBPP 293/418 (best so far; v7 289/285, Pinpoint 263-282), order/type failures 15 (v7 26/23);
  HumanEval 268 (v7 278/267, Pinpoint 282-286: a consistent gap). Next: hybrid (Pinpoint's flow
  for tasks with a signature, v7 + reorder for prose).

### 2026-10-25 — hybrid (Pinpoint's exact flow for tasks with a signature)

- `stub_profile="pinpoint_exact"` (`pinpoint_run`, verified line for line by a test): 274/350 on
  val HumanEval; Pinpoint control rerun today 280 (10-12 runs 282-286; v7 family 278/267/268).
  One HumanEval run varies by ±5. Second hybrid run 279 (mean 276.5 vs. v7 family 271), level
  with today's Pinpoint (280). Next: the full hybrid candidate on val.
  Smoke-70: 48/70, TDS 0.6607 (HumanEval 27/31, MBPP 21/39; v7 + reorder 50/70), within noise.
  Full val: TDS 0.6796, 542/768 (MBPP 272, HumanEval 270) vs. v7 + reorder 561: MBPP is the
  same code, so ±10 tasks of noise per run; HumanEval 274/279/270, no gain. v7 + reorder stays.
- `number_reference` (sign of negative numbers in digit tasks, off by default): 53, 54 of 72 on
  the digit tasks vs. control 53; the sign gets asked and answered, other requirements still fail.

### 2026-10-26 — KEY FINDING: the remaining failures are structural, not a formalization defect

- **What**: `scripts/injected_statements.py` (offline, no LLM) diffs every val variant against
  its unperturbed prompt and names its perturbation file; four val runs analysed.
- **Result**: per run, 17 failures on unperturbed tasks (the coder's floor); 64% of failures on
  tasks with 2+ hidden requirements; the largest class, HumanEval `larbi_contradictory` (19 of
  30 variants fail), is 14 wrong-type returns that obey an injected format statement which the
  perturbation also wrote into the type hints and the examples.
- **Reading it**: no signal in the prompt contradicts those statements; fixing them would mean
  ignoring the task in favour of the original benchmark (disqualified). Post-answer
  formalization can reach at most ~36 of ~210 failures, under one run's noise. Callout and
  details at the top of `docs/v7-failure-analysis.md`.
- `format_question` (ask about the return format when the task states one, off by default): 3, 6
  of 19 vs. control 5, 1 (earlier 3-4). The simulated user knows the right format (hidden
  requirements); our question presupposed the injected one (HumanEval/60: '15' or '12345'),
  and the coder overrode a correct answer when hints, doctests and text all said the opposite
  (HumanEval/36). Corrects the oracle claim of `d6ccf5b`. Example markers ("such as", "e.g.")
  do not hurt: answers with one pass 81.7% vs. 74.4%.
- `format_question="contrast"` (v2: contrastive readings, the answer overrides hints and
  examples): 5, 5 of 19 vs. control mean 3.2 and v1 4.5; HumanEval/60 now passes, but the audit
  still asks about another injected statement in about half of the variants.
- `format_question="dedicated"` (v3: plus one call that writes the contrastive question when no
  sampled one is): 7, 7 of 19, above all six controls (mean 3.2); the user answers "the
  integer, not the string" 5-7 times per run vs. 1. Expected +3-4 tasks per val run.
  HumanEval/65 (original says "as a string", 12 variants): v3 7, 5 vs. controls mean 6.5,
  within noise. Candidate: v7 + `reorder_arguments` + `format_question="dedicated"`.

### 2026-10-26 — candidate (v7 + reorder + format_question=dedicated) on val: TDS 0.6995

- 558/768 vs. v7 + reorder 561. On the 29 variants where the format trigger fires (the only
  ones where the code differs) 13 vs. 7-9 in four earlier runs; on the other 739, identical
  code, 545 vs. 553 (v7 r1 and r2 differ by 17 there).
- Second run: TDS 0.7144, 570/768 (best so far); trigger variants 14/29. Mean of two 564, TDS
  0.7070 vs. v7 + reorder 561 / 0.7033 and v7 559.5 / 0.7007. This is the submission candidate.
- Third run: TDS 0.7070, 564/768 (HumanEval 287, best of any run); trigger variants 11/29. Three
  runs: mean 564, TDS 0.7070 (0.6995-0.7144).

### 2026-10-28 — LAASeR_Evolution / LAASeR_Contrastive_Specs on smoke-70: TDS 0.357 / 0.372

- 26 and 27 of 70 vs. v7 + reorder 50 (0.687). Questions as good as v7's (QUALITY=3 in 52-53);
  the code fails (wrong value 23 vs. 12) because it is generated once, without v7's coding rules,
  sandbox checks and repairs. No val run; details in `docs/v7-failure-analysis.md`.

### 2026-10-31 — candidate selection headroom: +14 at most, about +3 realistic

- `scripts/candidate_dump.py` (v7 that records its three candidates) on val with the
  candidate's flags, scored per candidate by `scripts/candidate_headroom.py`: returned code
  558/765, a perfect selector 572, the three positions 543 / 549 / 542. All three agree in 727
  tasks; with 2 of 3 passing the returned code passes 15/18. Repair: +8, -0. No change made.
- The same run is the candidate's fourth val run: TDS 0.6998, 560/768; four runs mean 563,
  TDS 0.7052. Details: `docs/v7-failure-analysis.md`, update of 2026-10-31.

## Repo layout cheat-sheet

- `clarify/algorithms/LAASeRAlgorithm.py` — our submission (only file we're allowed to change for
  the actual submission PR).
- `tests/` — offline unit tests for our algorithm (dev tooling, not part of the submission).
- `scripts/evaluate.sh`, `scripts/make_report.py` — the one-command pipeline described above (dev
  tooling, not part of the submission).
- `scripts/validate_repository.py` — organizer-provided anti-cheat/metadata checker, run by CI.
- `results/history.csv` — one row per `scripts/evaluate.sh` run, our own progress log.
- `results/runs/<timestamp>_<label>/` — full artifacts (logs + jsonl + report.md) per run.
- `results/latest_report.md` — always the most recent run's report.
- `docs/data/leaderboard.csv` — the real public leaderboard (not ours to edit casually; only via
  `--submit` on `evaluate_responses.py`, which is a separate, deliberate action).
