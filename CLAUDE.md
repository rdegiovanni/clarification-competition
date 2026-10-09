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
