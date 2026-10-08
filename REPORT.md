# Findings log

Dated findings from `scripts/evaluate.sh` runs, kept separate from the per-run
auto-generated `results/runs/<run>/report.md` so the headline takeaways don't
get lost in run-by-run noise. See `results/history.csv` for the raw trend
and `CLAUDE.md` for how scoring/the pipeline works.

## 2026-10-08 — "no python code block returned" is the dominant failure mode at full `val` scale

**Run**: `scripts/evaluate.sh --split val --label val-full`, commit `c695a8c` (dirty),
`anthropic/claude-sonnet-5`, temperature 0.7, 770 tasks (official validation split).
Full artifacts: `results/runs/20261008T093742Z_val-full/`.

**Headline metrics**:

| Metric | Value |
|---|---|
| TDS | 0.7120 |
| nDCG | 0.0701 |
| Pass@1 | 71.56% |
| Clarification rate | 16.75% |
| Over-asking rate | 4.66% |
| Avg. cost/task | $0.008123 |

Breakdown: Mbpp 68.33% (287/420), HumanEval 75.43% (264/350).

**The finding**: of 220 failing results, **218 (99%) are "no python code block
returned"** — the model's response didn't contain a ` ```python ... ``` ` block
that `_validate_and_parse_evalplus_result` could parse, so the algorithm fell
through to `return candidate` with nothing to submit. This failure signature
existed in our first 30-task demo run too (`results/runs/20261008T084523Z_LAASeRAlgorithm/`),
but only accounted for 5/5 of that run's failures — at demo scale it looked
like one of several equally-plausible issues. At the full 770-task `val` scale
it's unambiguous: it is *the* problem, dwarfing every other failure reason
combined (the only other one is a single `evalplus` execution timeout).

**Secondary observations from the same run**, lower priority than the above
but worth tracking:

- Over-asking rate rose to 4.66% (it was 0.00% on the 30-task demo) — the
  algorithm is now measurably asking questions on tasks that didn't need one,
  which costs TDS/nDCG directly.
- Only 41.86% of clarification questions were rated high-quality (score 3) by
  the nDCG judge, which is why nDCG (0.0701) sits far below every public
  leaderboard entry. The lowest-ranked public baseline (`LLMClarification`)
  scores 0.0000 on nDCG, so a competitive TDS alone doesn't guarantee we clear
  that floor by a meaningful margin.

**Why this matters**: TDS (0.7120 this run) already looks good against the
public leaderboard (the current #1 entry sits at 0.6410 TDS) — but that
comparison uses a different model (`openai/gpt-4.1-mini` vs. our dev default
`anthropic/claude-sonnet-5`), so it's a compass, not a verdict (see
`CLAUDE.md`). Independent of that caveat, fixing "no python code block
returned" is the highest-leverage next change: at 218/770 (28.3% of *all*
tasks, not just failures), it is larger than the clarification rate itself.

**Suggested next step**: pull a handful of the 218 failing task IDs' raw
`generate.jsonl` entries from this run and inspect the model's actual response
text — confirm whether `READY_TO_CODE` is present without a fenced code block
(a prompting problem) vs. a fenced block in an unexpected format (a parsing
problem in `_validate_and_parse_evalplus_result`) before changing anything in
`LAASeRAlgorithm.py`. Per the repo's working rule, any resulting change still
needs a `scripts/evaluate.sh` before/after measurement.

**Correction (see 2026-10-08 entry below)**: the "218/220 no python code block
returned" headline above is **wrong** — it's an artifact of a mislabeling bug
in `scripts/make_report.py`'s `classify_failure()`, not a real description of
what happened on 218 tasks. Left in place (rather than rewritten) so the
decision log stays honest about what we actually believed and when; see below
for the corrected breakdown of this same run's failures.

## 2026-10-08 — Root cause of the gpt-4.1-mini "pésimo" smoke test: a reporting bug + a real entry-point naming bug

**Trigger**: ran `scripts/evaluate.sh --language-model openai/gpt-4.1-mini` (demo
set, 30 tasks) to get a leaderboard-comparable number. Result was much worse
than our Claude runs: TDS 0.5561, nDCG 0.3333, Pass@1 56.67%
(`results/runs/20261008T112852Z_gpt41mini-demo/`), with the report claiming
all 13 failures were "no python code block returned" — the same signature
the previous entry above flagged as *the* dominant failure mode at full
`val` scale (218/220). That repetition across two different models and two
different dataset scales was suspicious enough to warrant actually reading
the raw rows instead of trusting the report's label.

### Bug #1 (reporting only): `classify_failure()` mislabels almost everything as "no code block"

`_validate_and_parse_evalplus_result()` (`clarify/runtime.py`) **strips the
` ```python `/` ``` ` fence on success** — a successfully-parsed candidate's
saved `prompt_result` can therefore never contain the literal `` ```python ``
substring. `scripts/make_report.py`'s old `classify_failure()` used exactly
that substring as its test for "no code returned", so it mislabeled *every*
non-empty failing candidate — including ones whose code ran and simply failed
the hidden tests — as "no python code block returned".

Checking the actual `results.jsonl` rows (not just the report) for the
gpt-4.1-mini demo run: of its 13 failures, only **3** (`Mbpp/16, 56, 59`) had a
genuinely empty `prompt_result` — the rest (10/13) had real, non-empty code
that ran and failed (`AssertionError`/wrong output, `TypeError`, a
`NameError`). Re-checking the full `val`-scale Claude run
(`results/runs/20261008T093742Z_val-full/`) the same way: of its 219 failures,
only **35** are genuinely empty — the headline "218/220" in the entry above
undercounted "code ran but was wrong" by roughly 5x and should never have been
read as a parsing/prompting problem at that scale.

**Fix**: rewrote `classify_failure()` in `scripts/make_report.py` (dev
tooling, not `clarify/`, so in scope per `CLAUDE.md`) to key off
`prompt_result.strip() == ""` for "no code returned" instead of the fence
substring, and added a `NameError`-based "function name mismatch" bucket (see
bug #2). This only changes report *labels*, not scores — it's a correctness
fix for a dev tool, not a submission change, so it needed no before/after
`evaluate.sh` run on its own.

### Bug #2 (real, in our algorithm): the model is never told to keep the exact `entry_point` name

While re-checking the (now correctly labeled) `NameError` failures in the
`val`-full Claude run, a clear pattern emerged: **35 of 219 failures (16%)**
are `NameError: name '<entry_point>' is not defined`, where the submitted code
defines a *different*, syntactically-valid function. Example —
`HumanEval/6` (`entry_point` = `parse_nested_parens`): the task prompt in the
`humaneval_wu_ambiguous*` variant files presents the stub as
`def candidate(paren_string: str) -> List[int]:` instead of the real name.
The model (correctly, even) completed the stub exactly as shown, submitting
`def candidate(...)` — but the hidden tests call `parse_nested_parens(...)`,
so it fails every test regardless of whether the logic is right. 34/35 of
these are `HumanEval` tasks (one, `Mbpp/782`, is `Mbpp`); they're
concentrated in exactly the "ambiguous"/perturbed variant files that
rename the stub's function on purpose. Our `READY_TO_CODE_TEMPLATE` already
received `problem["entry_point"]` (the *correct* name, from the SDK, not from
the untrusted prompt text) but only used it as a label
("Task (function to implement: `{entry_point}`)") — nothing told the model
that name must win over whatever the prompt text itself shows.

**Fix**: added one explicit paragraph to `READY_TO_CODE_TEMPLATE` in
`clarify/algorithms/LAASeRAlgorithm.py`:

> Important: your final function must be named exactly `{entry_point}`, even if
> the task text above uses a different (e.g. generic or placeholder) name for
> it. The hidden tests call the function `{entry_point}` by that exact name, so
> any other name fails every test regardless of whether the logic is correct.

Deliberately did **not** also wrap `{prompt}` in a fresh triple-backtick fence
(the obvious companion fix for the already-broken single-backtick wrapping) —
`data/mbpp/mbpp_akli_syntax_and_formatting_sf.jsonl` has prompts that already
contain literal `` ``` `` as part of the perturbation (e.g. `Mbpp/2`'s prompt
starts with `` ```Write a function... ``), so adding our own triple-backtick
fence around `{prompt}` would self-close early on exactly that variant family.
Left for a future, separately-measured change.

### Before/after measurement

Per `CLAUDE.md`'s working rule, measured with `scripts/evaluate.sh` before
changing anything, demo set (30 tasks, Mbpp-only), `openai/gpt-4.1-mini`:

| Metric | Before (`acf8dfd`, `20261008T112852Z_gpt41mini-demo`) | After (`77b9204`+fix, `20261008T114353Z_gpt41mini-entrypointfix`) | Δ |
|---|---|---|---|
| TDS | 0.5561 | 0.4561 | ▼ -0.1000 |
| nDCG | 0.3333 | 0.5000 | ▲ +0.1667 |
| Pass@1 | 56.67% | 46.67% | ▼ -10.00pp |
| Clarification rate | 36.67% | 53.33% | ▲ +16.66pp |

**This is not evidence the fix hurts.** Two reasons, both expected going in:

1. **The demo set is Mbpp-only, and the entry-point bug we fixed is 34/35
   `HumanEval`** (the "ambiguous" stub-renaming variants live in
   `data/humaneval/`, not `data/mbpp/`) — this 30-task slice barely exercises
   the thing we changed. Confirmed directly: the new run's failures (16 total)
   break down as 9 "wrong output", 4 "other unhandled error", 3 genuinely "no
   code returned" — zero real function-name mismatches, same as before the
   fix. The fix was a no-op on this slice, as expected.
2. **`temperature=0.7` plus `n=30`** means a handful of unrelated tasks
   flipping pass/fail between runs moves TDS by ~0.03 each — `CLAUDE.md`
   already warns a single demo-scale before/after isn't proof of anything.
   The failing-task-ID sets only partially overlap between the two runs
   (`Mbpp/4, 14, 57, 62, 69` are new failures; `Mbpp/9, 61` newly pass),
   consistent with sampling noise, not a systematic regression from the
   prompt change.

**Correction**: the val-split confirmation run mentioned above was cancelled
before completing (explicit instruction, no results produced) in favor of the
new direction below — superseded, not finished.

## 2026-10-08 — LAASeR2Algorithm: a new submission file with a gate/solve split design

**Trigger**: still chasing the gpt-4.1-mini gap above. Rather than keep
patching `LAASeRAlgorithm.py`'s single combined "ready-or-ask" prompt loop,
designed a new, original file, `clarify/algorithms/LAASeR2Algorithm.py`
(`LAASeR2Algorithm`), rather than modifying the v1 submission in place —
different structure, naming, and templates, built around three changes:

1. **Separate the "ask" decision from "write code" into two independent LLM
   calls**, each with its own single-purpose prompt, instead of one combined
   prompt re-sent in a loop. v1's loop re-sends the same `READY_TO_CODE` /
   `QUESTION` prompt after an answer comes back, so there's a second point
   where the model can fail to repeat the right keyword and the loop falls
   through to an empty candidate. v2's gate step (`GATE_TEMPLATE`,
   `NO_QUESTION` / `QUESTION: ...`) runs at most once; the solve step
   (`SOLVE_TEMPLATE`) always runs after it, independent of what the gate said.
2. **Structurally validate the response before accepting it.**
   `_is_usable_solution()` parses the candidate with `ast` and checks for a
   top-level `FunctionDef`/`AsyncFunctionDef` node literally named
   `entry_point` — not just "is there a `python` fence". This directly
   targets both Bug #1 and Bug #2 above (an unparseable/wrongly-named
   candidate is now *detected*, not silently reported as "no code").
3. **Repair instead of giving up, and never return `""`.** On a bad
   candidate, v2 re-prompts up to `MAX_REPAIR_ATTEMPTS=2` times with a
   targeted repair message (append the bad response + "fix just the name/
   syntax" to the conversation) instead of returning immediately. If every
   attempt still fails, it returns a syntactically valid stub
   (`def {entry_point}(*args, **kwargs): raise NotImplementedError`) instead
   of `""` — guarantees "no code returned" can never happen again, by
   construction, independent of model behavior.

Passes `scripts/validate_repository.py` (anti-cheat/metadata check) and
`uvx ruff check` cleanly. New offline unit tests added,
`tests/test_laaser2_algorithm.py` (9 cases: gate asks/doesn't ask, repair
loop recovers from a wrong name, budget/turn limits mid-gate and mid-solve,
`ask_human` over-budget still proceeds to solve, repairs-exhausted fallback
is non-empty and correctly named) — all pass offline.

**Demo-scale result** (30 tasks, Mbpp-only, `openai/gpt-4.1-mini`,
`scripts/evaluate.sh --clarify-py clarify/algorithms/LAASeR2Algorithm.py
--language-model openai/gpt-4.1-mini --label lasser2-demo`, commit `11a486d`
dirty): `results/runs/20261008T115425Z_lasser2-demo/`.

| Metric | v1 baseline (`20261008T112852Z_gpt41mini-demo`) | v2 LAASeR2Algorithm (`20261008T115425Z_lasser2-demo`) | Δ |
|---|---|---|---|
| TDS | 0.5561 | **0.6402** | ▲ +0.0841 |
| nDCG | 0.3333 | **0.9000** | ▲ +0.5667 |
| Pass@1 | 56.67% | 66.67% | ▲ +10.00pp |
| Clarification rate | 36.67% | 100.00% | ▲ +63.33pp |
| Over-asking rate | 0.00% | 0.00% | = |
| Failure reasons | 9 wrong output, 4 other error, 3 no code | 8 wrong output, 2 other error, **0 no code, 0 NameError** | — |

0.6402 TDS at demo scale would sit essentially tied with the public #1 entry
(0.6410) — **but treat that as encouraging, not
proven**: this is a 30-task, Mbpp-only slice (same caveat as every demo run
in this file), it cannot exercise the HumanEval-concentrated entry-point bug
v2's `ast` check specifically targets (so that part of the design is
untested here), and `temperature=0.7` noise alone is worth a few points of
TDS at `n=30`. The 100% clarification rate is also worth watching — on this
slice over-asking rate stayed 0.00%, but a gate step asking on literally
every task is a pattern worth re-checking once a larger run makes
over-asking visible if it's happening (it costs nDCG/TDS directly per
`CLAUDE.md`).

**Decisive test launched**: `scripts/evaluate.sh --split val --clarify-py
clarify/algorithms/LAASeR2Algorithm.py --language-model openai/gpt-4.1-mini
--label lasser2-val` (770 tasks, mixed Mbpp+HumanEval — the only way to
measure whether the `ast`/entry-point fix actually earns its keep, and to
get a clarification-rate number not dominated by one small Mbpp-only
sample). Will append the result here once it completes.
