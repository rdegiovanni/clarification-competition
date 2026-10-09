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
before completing (explicit instruction, no results produced) — superseded,
not finished.

## 2026-10-09 — Fase 1 failure analysis + first Fase 3 challenger (`LAASeR_RepairV2`): does not beat the champion

**Fase 1 deliverable**: `docs/failure-analysis.md`, built from a 30-task two-class smoke set
(seed 42, `openai/gpt-4.1-mini`), 3 runs each for the champion `LAASeR_Repair`,
`LAASeRAlgorithm`, `LAASeR3Algorithm`, and the organizer `LLMClarification` baseline. Found and
fixed a real bug in our own `scripts/compare_runs.py` diagnostics along the way (it was comparing
a task id against algorithm-label dict keys instead of checking label membership, so universal-
failure/oracle-rate numbers were silently always zero). Headline: 6/30 tasks fail for every
algorithm we have data for (`HumanEval/139, Mbpp/143, Mbpp/229, Mbpp/26, Mbpp/559, Mbpp/759`),
oracle rate (solved by at least one algorithm) is 24/30 (80%). Full per-task root-cause writeup,
cross-algorithm architecture notes, and a prioritized Fase 3 hypothesis list are in that doc.

**Separately, a real operational hazard found while screening the first Fase 3 challenger**: a
single huge-int task (`HumanEval/139`) can crash an *entire* `evaluate_responses.py` batch,
discarding every other task's result, unless `PYTHONINTMAXSTRDIGITS=0` is exported in the shell
first — reproduced directly (crashed at 12/30 without the env var, completed cleanly at 30/30
with it). Documented in `CLAUDE.md`'s Known SDK quirks section and `docs/failure-analysis.md`'s
`HumanEval/139` entry; not a fix to the task itself (organizer-owned sandbox), just a workaround
so one task can't take down a whole run's data.

**Fase 3 challenger #1**: `clarify/algorithms/laaser_repair_v2.py` (`LAASeR_RepairV2`) — a repair-
loop variant with a hard `MAX_REPAIR_ATTEMPTS` cap, a `best_parseable_code` fallback instead of
discarding an unusable response outright, explicit `NO_KEYWORD` status handling, and an anchored
question-detection regex. Same 30-task seed-42 smoke set, 3 runs, `openai/gpt-4.1-mini`:

| Run | TDS | Pass@1 |
|---|---|---|
| r1 | 0.6667 | 66.67% |
| r2 | 0.7000 | 70.00% |
| r3 | 0.6667 | 66.67% |
| **mean ± stdev** | **0.6778 ± 0.0192** | **67.78% ± 1.92pp** |

Champion `LAASeR_Repair` on the identical 3-seed setup: TDS 0.7222 ± 0.0192, Pass@1 72.22% ±
1.92pp (runs 0.7333/0.7000/0.7333). The gap (0.044 TDS) exceeds either group's stdev and holds
across all 3 runs — every `LAASeR_RepairV2` run is at or below the champion's *lowest* run, and
2 of 3 are strictly worse than every champion run. Over-asking stayed at 0.00% in both, so this
isn't a case of trading over-asking for pass rate either way. Task-matrix diff: `RepairV2`'s most
recent run newly loses `HumanEval/6` relative to the champion (plus the two already-known
noise-flip tasks `HumanEval/154`/`Mbpp/755`), gains nothing back.

**Verdict**: `LAASeR_RepairV2` does **not** beat the champion — real, held signal, not noise.
Per the mission's non-negotiable rules it is **kept, not deleted**, as a documented losing
variant (experiment #1 of the Fase-3 safety cap). Moving on to the Fase 3 hypothesis list's #1
item next (signature/arity clarifying question for stub-less MBPP tasks — targets `Mbpp/229`/
`Mbpp/559` directly, the single strongest multi-instance pattern found in the Fase 1 analysis).

## 2026-10-09 — Fase 3 challenger #2 (`LAASeR_Signature`): also does not beat the champion, and doesn't even fix what it targeted

**Fase 3 challenger #2**: `clarify/algorithms/laaser_signature.py` (`LAASeR_Signature`) — hypothesis
#1 from `docs/failure-analysis.md`'s prioritized list. Structurally an exact copy of the champion
`LAASeR_Repair` (same repair loop, same format/entry-point/parsing-error recovery) with exactly one
isolated change: an added paragraph in `READY_TO_CODE_TEMPLATE` warning the model not to assume a
function's parameter list from prose alone when no stub/signature is shown, and framing that
uncertainty itself as a valid reason to ask. Targeted directly at `Mbpp/229`/`Mbpp/559` (the
`(arr, n)`-style implicit-arity pattern documented in Fase 1). Same 30-task seed-42 smoke set, 3
runs, `openai/gpt-4.1-mini`:

| Run | TDS | Pass@1 | Clarification rate |
|---|---|---|---|
| r1 | 0.6640 | 66.67% | 16.67% |
| r2 | 0.6640 | 66.67% | 13.33% |
| r3 | 0.6640 | 66.67% | 13.33% |
| **mean ± stdev** | **0.6640 ± 0.0000** | **66.67% ± 0.00pp** | **15.56% ± 1.93pp** |

Champion `LAASeR_Repair` on the identical 3-seed setup: TDS 0.7222 ± 0.0192, Pass@1 72.22% ±
1.92pp, clarification rate 3.33%. The gap (0.058 TDS) exceeds either group's stdev and holds
across all 3 runs — every `LAASeR_Signature` run is below the champion's *lowest* run. Over-asking
stayed at 0.00% in both (the extra questions aren't being flagged as unwarranted by the harness),
but the clarification rate nearly 5x'd (3.33% → 15.56% mean) with no corresponding Pass@1 gain —
the extra turns cost TDS directly via the turn-discount even where the eventual answer was still
correct.

**The hypothesis itself failed empirically, not just the net score**: checked `clarification_history`
for `Mbpp/229`/`Mbpp/559` directly in all 3 runs' `results.jsonl` — the model **never asked** about
either task in any of the 3 runs (`clarification_history: []` throughout, identical to the
champion). The added warning paragraph did make the model ask more *elsewhere*, but not on the two
specific tasks it was written for. Task-matrix diff (most recent run vs. champion): `Signature`
newly loses `HumanEval/154`, `Mbpp/755`, and `Mbpp/914` (all three pass under the champion), and
recovers nothing. Full matrix: `results/internal_leaderboard.md`.

**Verdict**: `LAASeR_Signature` does **not** beat the champion — a clear regression, held across
all 3 runs (in fact zero inter-run variance on TDS/Pass@1, a stronger signal than usual noise would
produce), and it fails to achieve the one thing it was built for. Kept, not deleted, as experiment
#2 of the Fase-3 safety cap (2 of 25 experiments used, 2 consecutive non-improving). Takeaway for
future attempts at this same hypothesis: a generic "ask if the signature is uncertain" nudge isn't
enough to make the model actually ask on these two specific tasks — the prose for `Mbpp/229`/
`Mbpp/559` apparently reads as fully-specified to the model even with the warning in place, and the
nudge's main side effect was indiscriminately raising the ask rate elsewhere instead. A future
attempt would need something more targeted (e.g. explicitly flagging the "redundant array-length
parameter" convention by name, or detecting array/list-typed prompts with no stub as a trigger)
rather than a generic epistemic-humility warning. Moving on to the Fase 3 hypothesis list's #3 item
next (standalone entry-point/signature-trust wording strengthening, measured in isolation) since
#2 (self-verification) is more expensive and #1's natural next iteration needs more thought before
spending another experiment slot on it.
