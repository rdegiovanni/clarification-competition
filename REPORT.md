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

## 2026-10-09 — Fase 3 challenger #3 (`LAASeR_EntryTrust`): third consecutive non-improving result

**Fase 3 challenger #3**: `clarify/algorithms/laaser_entrytrust.py` (`LAASeR_EntryTrust`) —
hypothesis #3 from `docs/failure-analysis.md`'s prioritized list. Structurally an exact copy of the
champion `LAASeR_Repair` with exactly one isolated change: the champion's one-line entry-point
reminder in `READY_TO_CODE_TEMPLATE` is replaced with the stronger, more explicit wording already
used in the older `LAASeRAlgorithm.py` ("even if the task text above uses a different name for it
... any other name fails every test regardless of whether the logic is correct"). Idea was to close
the wording gap between our two existing algorithms and see if the stronger phrasing reduces
entry-point-name mismatches. Same 30-task seed-42 smoke set, 3 runs, `openai/gpt-4.1-mini`:

| Run | TDS | Pass@1 | Clarification rate |
|---|---|---|---|
| r1 | 0.6667 | 66.67% | 6.67% |
| r2 | 0.6667 | 66.67% | 6.67% |
| r3 | 0.6333 | 63.33% | 6.67% |
| **mean ± stdev** | **0.6556 ± 0.0193** | **65.56% ± 1.93pp** | **6.67% ± 0.00pp** |

Champion `LAASeR_Repair` on the identical 3-seed setup: TDS 0.7222 ± 0.0192, Pass@1 72.22% ±
1.92pp, clarification rate 3.33%. The gap (0.0666 TDS) exceeds either group's stdev and holds
across all 3 runs — every `LAASeR_EntryTrust` run is at or below the champion's *lowest* run.
Over-asking stayed at 0.00% in both.

**Task-matrix diff** (most recent run vs. champion, full matrix in
`results/internal_leaderboard.md`): `EntryTrust` newly loses `HumanEval/129`, `HumanEval/154`,
`Mbpp/755`, and `Mbpp/90` (all four pass under the champion) and recovers nothing. None of the
6 universal failures this smoke sample has always had (`HumanEval/139`, `Mbpp/143`, `Mbpp/229`,
`Mbpp/26`, `Mbpp/559`, `Mbpp/759`) are entry-point-name mismatches in the first place — this
30-task sample simply doesn't contain any of the "ambiguous stub renames the function" `HumanEval`
variant tasks the original wording-gap bug (documented earlier in this file, 2026-10-08) was found
on at full `val` scale. So the stronger wording had no failure mode to fix in this sample, and its
only measurable effect was the same kind of side-effect regression seen with challenger #2: making
the prompt longer/more emphatic nudges the model's behavior elsewhere in ways that cost a few tasks
without recovering any.

**Verdict**: `LAASeR_EntryTrust` does **not** beat the champion. Kept, not deleted, as experiment
#3 of the Fase-3 safety cap (3 of 25 experiments used). **This is now 3 consecutive non-improving
experiments** (`LAASeR_RepairV2`, `LAASeR_Signature`, `LAASeR_EntryTrust`) — one short of the
4-consecutive-non-improving stop threshold in the mission's safety cap. Takeaway: isolated wording
tweaks to the champion's existing prompt, measured on this particular 30-task smoke sample, keep
producing the same shape of result — no measurable fix (because the sample doesn't exercise the
targeted failure mode) plus a small, consistent regression elsewhere from the added prompt text.
Before spending a 4th consecutive slot on another small wording variant, the next attempt should
either (a) target a failure mode that is actually *present* in this smoke sample (not just at full
`val` scale), or (b) test the current best candidates (`LAASeR_RepairV2`, `LAASeR_Signature`,
`LAASeR_EntryTrust`) against a different task sample/seed to check whether the champion's edge is
sample-specific before concluding these variants are categorically worse.

## 2026-10-09 — Fase 3 challenger four (`LAASeR_ConcreteQuestion`): fourth consecutive non-improving result, safety cap reached

**Hypothesis**: rather than changing *whether* the champion asks a clarifying question (the
generic nudge direction already tried and already backfired in challenger two), target *what* the
question looks like on cases where the model was already going to ask anyway. Grounded directly in
the Fase 1 failure analysis for `Mbpp/26`: the champion already asks on that task, but the question
it asks is abstract/definitional ("what is the parameter k, and what elements should be checked
against the tuples?"), gets a confidently-stated but wrong answer, and fails anyway. The new
variant adds one paragraph to the existing `READY_TO_CODE_TEMPLATE` telling the model that, if it
does ask, it should prefer a concrete input/output example over an abstract description — nothing
else changes versus the champion `LAASeR_Repair`.

**3-run result** (same 30-task smoke set, seed 42, `openai/gpt-4.1-mini`, temperature 0.7):

| Run | TDS | nDCG | Pass@1 | Clarification rate |
|---|---|---|---|---|
| r1 | 0.6987 | 0.1000 | 70.00% | 10.00% |
| r2 | 0.6653 | 0.1000 | 66.67% | 10.00% |
| r3 | 0.6987 | 0.0667 | 70.00% | 10.00% |
| **Mean ± stdev** | **0.6876 ± 0.0193** | 0.0889 ± 0.0192 | **68.89% ± 1.92pp** | **10.00% ± 0.00pp** |

Champion `LAASeR_Repair` on the identical setup: TDS 0.7222 ± 0.0192, Pass@1 72.22% ± 1.92pp,
clarification rate 3.33%. The gap (0.0346 TDS) exceeds either group's stdev and holds across all 3
runs.

**Direct inspection of the mechanism** (per the falsification discipline established after
challenger two): checked `clarification_history` for every task that asks a question in all 3 runs.
The nudge is consistently reproducible — all 3 runs ask on exactly the same 3 tasks, every time:

- `Mbpp/26` (the actually-targeted task): the model now reliably asks for a concrete input/output
  example instead of an abstract definition, exactly as intended — but the simulated human's
  answer is itself inconsistent/wrong relative to the real spec in all 3 runs, so the task still
  fails. The content of the question changed as designed; it did not change the outcome.
- `Mbpp/251`: **new side effect.** The champion never asks on this task (confirmed by checking the
  champion's own clarification history for the same task across its 3 runs) and passes directly.
  `LAASeR_ConcreteQuestion` now asks here too — the task still passes, but the extra turn applies
  the TDS turn-discount for no benefit.
- `Mbpp/759`: **new side effect.** Same pattern — champion never asks and still fails; this variant
  now asks too, with no change in outcome (still fails) and an extra wasted turn.

So three runs' worth of evidence converges on the same explanation challenger two already surfaced:
a prompt change aimed at nudging clarification behavior reliably spills over into asking on tasks
it was never meant to touch, even when the change is scoped to question *content* rather than
*whether to ask*. The clarification rate roughly tripling (3.33% → 10.00%) is the direct, measured
cost of that spillover; the one task it was designed to help shows no benefit at all because the
simulated human's answer quality — not the question's phrasing — was the actual bottleneck.

**Verdict**: `LAASeR_ConcreteQuestion` does **not** beat the champion. Kept, not deleted, as
experiment four of the Fase-3 safety cap (4 of 25 experiments used). **This is now four
consecutive non-improving experiments** (`LAASeR_RepairV2`, `LAASeR_Signature`,
`LAASeR_EntryTrust`, `LAASeR_ConcreteQuestion`) — this meets the mission's safety-cap stop
condition (4 consecutive non-improving). Per the mission rules, Fase 3 experimentation on direct
prompt-wording variants of the champion should pause here for a checkpoint with the team rather
than silently continuing to a fifth attempt. Two converging reasons stand out from four straight
experiments: (1) every failing task in this particular 30-task smoke sample that the champion
already gets right either depends on the simulated human answering well (not on how the question
is worded) or is a universal failure no wording change reaches; and (2) any prompt addition that
tries to influence clarification behavior — more assertive, more wording-specific, or more
example-oriented — measurably increases the ask rate on tasks that didn't need it, at a real TDS
cost, without yet producing a single clear win. The open question for the team: keep iterating on
champion-prompt variants against this same 30-task sample, or pivot to testing current candidates
against a different seed/sample (to rule out this specific sample being an unfavorable one for any
wording change), or explore a structurally different approach (e.g. the `LAASeR3Algorithm`/evidence
-gated plan already drafted) instead of further prompt-only tweaks.

**Checkpoint decision**: at this four-consecutive-non-improving stop point, the call was made to
pause automatic Fase 3 experimentation here rather than keep spending runs on more wording
variants, a different seed, or a structural pivot. `LAASeR_Repair` remains the champion
(TDS 0.7222 ± 0.0192 on this smoke sample). All four non-improving challengers
(`LAASeR_RepairV2`, `LAASeR_Signature`, `LAASeR_EntryTrust`, `LAASeR_ConcreteQuestion`) are kept in
`clarify/algorithms/` per the mission rules, not deleted. Next steps are for the team to decide
before any further experiment is launched.

## 2026-10-09 — Fase 3 challenger five (`LAASeR_Gate`): first structural pivot, loses on net score but confirms a major mechanism

**Hypothesis**: at the checkpoint above, the team's own read of `clarify/env.py`'s simulated-human
system prompt (`HUMAN_SYSTEM_PROMPT`) revealed *why* the champion's `Mbpp/26` question failed: the
simulated human grades every question against five criteria (CRITICALITY / SEARCH SPACE / LEAKAGE
/ ATOMICITY / OBJECTIVITY) before answering, and a question that bundles two sub-asks ("what is
the parameter k, **and** what elements should be checked?") fails ATOMICITY, which the prompt's
own rules say gets a deliberately vague, non-committal answer rather than a precise one. Separately,
`laaser_signature.py`'s generic "don't assume the parameter list" warning had already been shown
(challenger #2) to never actually fire on the arity-ambiguous tasks it targeted. `LAASeR_Gate`
(`clarify/algorithms/laaser_gate.py`) attacks both with one structural change — splitting the
champion's single "decide to ask or code" call into two: a **DRAFT** call that writes the
candidate plus a self-reported `ASSUMPTIONS:` list of anything inferred but not stated in the
task text, and a **GATE** call that is shown the draft and its own assumptions and must pick at
most one that would actually change correctness, asking a single atomic, concrete, closed-form
question about it (or `DONE` if none would).

**3-run result** (same 30-task smoke set, seed 42, `openai/gpt-4.1-mini`, temperature 0.7):

| Run | TDS | nDCG | Pass@1 | Clarification rate | Cost/task |
|---|---|---|---|---|---|
| r1 | 0.6082 | 1.0000 | 63.33% | 100.00% | $0.001315 |
| r2 | 0.6402 | 0.9667 | 66.67% | 100.00% | $0.001294 |
| r3 | 0.5762 | 1.0000 | 60.00% | 100.00% | $0.001309 |
| **Mean ± stdev** | **0.6174 ± 0.0320** | **0.9889 ± 0.0192** | **64.44% ± 3.34pp** | **100.00% ± 0.00pp** | **$0.001306** |

Champion `LAASeR_Repair` on the identical setup: TDS 0.7222 ± 0.0192, nDCG 0.0333 ± 0.0000,
Pass@1 72.22% ± 1.92pp, clarification rate 3.33%, cost/task $0.000289. The TDS gap (0.1048)
exceeds either group's stdev and holds across all 3 runs — `LAASeR_Gate` does **not** beat the
champion, and costs ~4.5x more per task (two LLM calls per round instead of one; flagged per the
mission's cost-tracking rule, though 4.5x is modest next to ClarifyGPT's ~34x).

**Mechanism check, two findings, one confirmed strongly and one still unresolved:**

1. **Confirmed, strong**: the atomic/concrete-question design works almost perfectly against the
   simulated human's real rubric. Across all 90 questions asked in the 3 runs (30 tasks × 3 runs,
   100% clarification rate), **89/90 scored QUALITY=3** (the one QUALITY=1 outlier was in r2); mean
   nDCG 0.9889 vs. the champion's 0.0333 — a ~30x improvement in question quality. Directly
   verified on the previously-documented `Mbpp/26` case: this time the question is single-fact and
   concrete ("If the input is `check_k_elements([(1, 2), (2, 3)], 3)`, should the function return
   True?") and gets back a precise, confident, QUALITY=3 answer — the exact failure mode the user
   flagged (abstract/bundled question → vague wrong answer) is gone at the question-quality level.
   `HumanEval/55` — the case `docs/failure-analysis.md` explicitly flagged as *not fixable* by
   self-verification against the prompt's own doctests (the hidden test exercises an edge case the
   stated doctests don't cover) — is fixed here directly by asking: `Should fib(0) return 0, 1, or
   raise an error?` → `fib(0) should return 0` → the task now passes. A real, mechanism-level win.
2. **Still unresolved**: the gate essentially never says `DONE` — 100.00% clarification rate in all
   3 runs, 0 occurrences of "no question" observed. Forcing the DRAFT step to always produce an
   `ASSUMPTIONS:` list gives the GATE step something plausible-sounding to flag on *every* task,
   including ones the champion already solves without asking — that's the direct cost behind the
   Pass@1 drop (64.44% vs 72.22%). Task-level diff (r3 vs. the champion's most recent matching run):
   `LAASeR_Gate` newly loses `Mbpp/115, Mbpp/251, Mbpp/755, Mbpp/90, HumanEval/7, HumanEval/6` (all
   six pass under the champion) and newly gains `HumanEval/108, HumanEval/55` — net -4 tasks, this
   over-asking cost outweighing the quality win on this sample. Separately, the signature/arity
   hypothesis (challenger #2's original target) is **still not solved**: on `Mbpp/229` the gate asks
   about zero-handling, and on `Mbpp/559` about empty-list behavior — real, atomic, QUALITY=3
   questions, but neither is the actual missing-parameter root cause from `docs/failure-analysis.md`.
   The model's self-reported `ASSUMPTIONS:` list apparently never spontaneously includes "there may
   be a parameter the text never names" as a candidate — the same blind spot `laaser_signature.py`
   had, just relocated one level up (into what counts as a self-reported assumption rather than
   into a generic warning).

**Verdict**: `LAASeR_Gate` does **not** beat the champion on net score — kept, not deleted, per the
mission's rules, logged as experiment five. Unlike challengers #1–#4, this is not a clean "no
effect" result: it isolates the real lever (question *atomicity*, confirmed with a ~30x nDCG
improvement and one concrete Pass@1 win on `HumanEval/55`) from the real cost (an under-selective
gate that asks on everything). The natural next iteration is **not** another full architecture
change, but tightening the GATE call's bar for asking — e.g. explicit cost-framing ("asking costs
you this task's turn-discount; only ask if the two most likely interpretations of this assumption
would make the candidate behave *differently* on a case the task text could plausibly test") —
plus giving the DRAFT step's `ASSUMPTIONS:` prompt an explicit, named prompt to consider "a
parameter the text never names" as its own assumption category, rather than leaving it to be found
incidentally. Not yet attempted; next experiment slot.

## 2026-10-10 — Fase 3 challenger eight (`LAASeR_GateV4`): forced signature check fixes one task cleanly, but the trigger is too broad and surfaces a deeper dataset limit

**Hypothesis**: `LAASeR_GateV3`'s mechanism check on `Mbpp/229` showed a hard ceiling for
self-report-based discovery — the model's `ASSUMPTIONS:` list never contains "there might be an
unmentioned second parameter" for that task, because the prompt text gives no textual basis to
generate it. `LAASeR_GateV4` (`clarify/algorithms/laaser_gate_v4.py`) stops relying on self-report
for this specific class: a deterministic, AST-based check (`_detect_unstated_arity_risk`) runs once
right after the first successful draft — if the prompt shows no function stub at all and the
drafted candidate's entry point takes exactly one argument used like a sequence (`len()`, indexing,
iteration), a fixed, pre-written, atomic question is asked directly, no LLM call and no
`env.exec_code` call needed for the check itself.

**3-run result** (same 30-task smoke set, seed 42, `openai/gpt-4.1-mini`, temperature 0.7):

| Run | TDS | nDCG | Pass@1 | Clarification rate |
|---|---|---|---|---|
| r1 | 0.6841 | 0.5667 | 70.00% | 66.67% |
| r2 | 0.6455 | 0.7333 | 66.67% | 76.67% |
| r3 | 0.6455 | 0.7667 | 66.67% | 80.00% |
| **Mean ± stdev** | **0.6584 ± 0.0223** | **0.6889 ± 0.1071** | **67.78% ± 1.92pp** | **74.45% ± 6.94pp** |

For reference: v3 TDS 0.6708 ± 0.0186 (nDCG 0.5889, clarification rate 61.11%); champion TDS
0.7160 ± 0.0200. `LAASeR_GateV4`'s mean TDS (0.6584) is slightly *below* v3's, within the combined
stdev of the two (not a confirmed regression, but not a confirmed win either) — nDCG and
clarification rate both rose substantially instead. Net task-level diff (r3 vs. the champion's
matched run): loses `Mbpp/251, 755, 90`, `HumanEval/154`, gains `HumanEval/108, 55` — net -2,
similar to v3's -1.

**Mechanism check — one clean, confirmed win, and two findings explaining why it didn't move TDS more:**

1. **Confirmed win: `Mbpp/559` is fixed cleanly, every run.** The forced question ("does
   `max_sub_array_sum` take exactly one argument, or also a second — e.g. the length?") gets the
   *correct* answer every time ("takes exactly two arguments: the array and its length"), the model
   correctly redrafts `def max_sub_array_sum(arr, length):`, and the `TypeError` is gone for good —
   the task now fails on a *different*, genuine logic bug (the classic Kadane's-algorithm
   convention of returning 0 when every element is negative, unrelated to clarification at all).
   This is the first time any challenger has actually closed the specific gap `Mbpp/229`/`Mbpp/559`
   were chosen to represent.
2. **The trigger fires far more broadly than the 2 tasks it targeted.** Checking every task where
   the forced question appears across all 3 runs: `Mbpp/115, 760, 229, 143, 755, 105, 914, 559`
   (and `Mbpp/759` in one run) — 7-8 tasks per run, most of which (`Mbpp/115, 760, 105, 914`) were
   *already passing* under the champion and under v3, and get asked anyway because any
   single-sequence-argument MBPP task with no stub shown matches the structural pattern, not just
   the specific `(arr, n)`-convention ones. Each of those adds the turn-discount penalty for zero
   benefit — this is almost certainly why TDS didn't move up alongside nDCG/clarification rate: the
   `Mbpp/559` win is being offset by over-triggering elsewhere. The heuristic needs to be narrower
   before this is a net win, not just mechanistically correct where it fires on the right task.
3. **`Mbpp/229` still fails, and the reason is more interesting than a wrong guess by the model —
   the simulated human doesn't actually know the answer either.** Checked the raw smoke-dataset
   record for both `Mbpp/229` and `Mbpp/559` directly: **neither has a `clarifications` or
   `reference_prompt` field** — only `prompt`, `entry_point`, `test_cases`. Per
   `clarify/env.py`'s `_build_human_system_prompt`, that means the simulated human's "Hidden
   Requirements" section literally renders as `[REDACTED]` for *both* tasks — the judge has no more
   information than our own generating model does. Since both tasks are in the same situation yet
   one gets a correct guess and the other doesn't, the real explanation is that the judge LLM is
   also just guessing from its own training-data familiarity with the underlying classic problem:
   "maximum sum contiguous subarray" (Kadane's algorithm) is an extremely common tutorial/LeetCode
   problem usually taught with an `(arr, n)` signature, so the judge's guess happens to land on the
   real convention; "re-arrange array so negatives come before positives" is less canonical, and the
   judge's guess lands on the same "obvious" one-argument reading our model also makes. **For these
   specific tasks, asking doesn't resolve an information asymmetry — there isn't one.** Both sides
   are guessing from the same kind of prior knowledge, and whether asking helps is a coin flip tied
   to how textbook-famous the specific problem happens to be. This is a dataset-authoring gap (a
   missing `clarifications` field for these records), not something fixable from our side of the
   algorithm.

**Verdict**: `LAASeR_GateV4` does **not** confirm a win over v3 or the champion — kept, not
deleted, logged as experiment eight. Real, demonstrated proof that the forced-check *mechanism*
works exactly as designed when it matters (`Mbpp/559`), but the current trigger condition (any
stub-less single-sequence-argument function) is too broad and the resulting over-asking cost
roughly cancels the gain on this sample. Next step, not yet attempted: narrow the trigger (e.g.
only fire when the candidate's single-argument usage pattern specifically resembles the
`(collection, count)` convention gap rather than any sequence usage at all) before concluding
whether the forced-check idea nets positive. Separately, a `--split val` run of this exact
candidate was launched independently by the team outside this session to get a first anti-overfitting
read; its result should be folded into this entry or a follow-up once available.

## 2026-10-10 — Fase 3 challenger seven (`LAASeR_GateV3`): multi-hypothesis discovery closes more of the gap, still short of the champion

**Hypothesis**: re-reading the full CONTRA methodology (not just the abstract) at the user's
request confirmed `LAASeR_GateV2` was a materially simplified version of the paper's actual
pipeline — the paper discovers *many* candidate questions and qualifies all of them in parallel
before selecting one, while v2 collapsed this to "the DRAFT step's one self-picked assumption →
verify it." `scripts/analyze_failures.py`'s taxonomy confirmed this costs recall concretely: v2
asked about the signature/arity bug class only 2/6 times vs. v1's 6/6. `LAASeR_GateV3`
(`clarify/algorithms/laaser_gate_v3.py`) closes that gap: the ALT+PROBE call may return up to 3
candidate hypotheses (one per uncertain assumption, most-to-least-uncertain order) in a single
response, all qualified in one combined `env.exec_code` probe script, and the question asked
belongs to the first candidate (in listed order) with a confirmed divergence — same cost shape as
v2 (one extra LLM call, one extra `exec_code` call per round), more recall.

**3-run result** (same 30-task smoke set, seed 42, `openai/gpt-4.1-mini`, temperature 0.7):

| Run | TDS | nDCG | Pass@1 | Clarification rate |
|---|---|---|---|---|
| r1 | 0.6494 | 0.6000 | 66.67% | 63.33% |
| r2 | 0.6801 | 0.5667 | 70.00% | 60.00% |
| r3 | 0.6828 | 0.6000 | 70.00% | 60.00% |
| **Mean ± stdev** | **0.6708 ± 0.0186** | **0.5889 ± 0.0192** | **68.89% ± 1.92pp** | **61.11% ± 1.92pp** |

A clear, monotonic progression across all three structural iterations on this smoke sample:

| | TDS | nDCG | Clarification rate |
|---|---|---|---|
| Champion `LAASeR_Repair` (4 runs) | 0.7160 ± 0.0200 | 0.0500 ± 0.0334 | 5.00% ± 3.34pp |
| v1 `LAASeR_Gate` | 0.6174 ± 0.0320 | 0.9889 ± 0.0192 | 100.00% ± 0.00pp |
| v2 `LAASeR_GateV2` | 0.6432 ± 0.0344 | 0.4333 ± 0.0882 | 43.33% ± 8.82pp |
| v3 `LAASeR_GateV3` | **0.6708 ± 0.0186** | 0.5889 ± 0.0192 | 61.11% ± 1.92pp |

`LAASeR_GateV3` does **not** beat the champion — the gap (0.0452) still exceeds the combined
stdev and holds across all 3 runs — but it is the closest any Gate variant has gotten, and the
tightest inter-run stdev of the three (0.0186, vs. v2's 0.0344), suggesting the multi-hypothesis
mechanism is also more *stable* than testing a single self-picked assumption.

**Mechanism check** (`scripts/analyze_failures.py` across all 3 runs, 90 rows): the signature/arity
class is asked about 3/6 times now, up from v2's 2/6 (still short of v1's 6/6) — multi-hypothesis
testing does recover some of the lost recall, but not all of it, because of a deeper issue the user
surfaced directly: for `Mbpp/229` specifically (prompt: *"Write a function to re-arrange the
elements of the given array so that all negative elements appear before positive ones"*, no stub
shown), checking the model's drafted candidate confirms it is a single-argument function
(`def re_arrange_array(arr):`) and `Mbpp/229` **still never asks in any of the 3 runs** — not
because the hypothesis loses out to competing candidates, but because the model's own
self-reported `ASSUMPTIONS:` list apparently never contains "there might be an unmentioned second
parameter" as a candidate for this task at all. **This is a real, structural ceiling on the whole
self-report-based discovery approach**, not a tuning problem: the task text gives no textual signal
whatsoever that a second parameter exists (confirmed directly against `data/mbpp/mbpp_original.jsonl`
— the hidden test calls `re_arrange_array([-1, 2, -3, 4, 5, 6, -7, 8, 9], 9)`, an MBPP convention
never implied by the prose). No amount of asking the model to introspect harder will produce an
assumption it has no textual basis to generate in the first place.

**Net task-level diff** (r3 vs. the champion's matched run): loses `Mbpp/755, Mbpp/90,
HumanEval/154`, gains `HumanEval/108, HumanEval/55` — net -1, the smallest gap yet (v1: -4, v2: -3).
`Mbpp/90` (the regression documented in the 2026-10-10 failure-analysis refresh) is still broken in
2 of 3 runs, now with a *mix* of `AttributeError` and `TypeError`, and is now asked about in all 3
runs without being fixed — asking happens, but not about the right thing, same pattern as `Mbpp/26`
and `Mbpp/559` below.

**Verdict**: `LAASeR_GateV3` does **not** beat the champion — kept, not deleted, logged as
experiment seven. Real, monotonic progress across all three structural iterations (TDS 0.6174 →
0.6432 → 0.6708), and the tightest variance yet. The next lever is not another tuning pass on
self-report-based discovery — the `Mbpp/229` mechanism check shows that approach has a hard ceiling
when the ambiguity leaves literally no textual trace. The proposed next step (not yet implemented):
a **forced, structural signature-candidate** — generated unconditionally whenever a task shows no
stub and operates on a sequence type, independent of whether the model's own self-report mentions
it, verified by the same execution check as every other candidate, and kept as its own atomic
question (explicitly *not* appended to any other question asked, to protect the validated
ATOMICITY win from challenger #5/#6).

## 2026-10-10 — Fase 3 challenger six (`LAASeR_GateV2`): execution-verified gate cuts over-asking by more than half, still short of the champion

**Hypothesis**: before designing this challenger, searched for related published work (per the
team's request) and found **CONTRA** ("Discovering and Qualifying Behavior-Changing Questions for
Selective Clarification in LLM Code Generation", arXiv:2610.01769) — its stated premise is almost a
diagnosis of challenger #5's failure: rather than trust an LLM's own "this assumption is critical"
self-report, generate two candidates under two plausible answers and only keep a question if they
**actually diverge in behavior** on shared inputs. `LAASeR_GateV2`
(`clarify/algorithms/laaser_gate_v2.py`) keeps v1's validated atomic/concrete question template but
replaces its self-judged GATE call with this execution-grounded check: the model proposes one
alternative candidate for the single assumption it is least sure about, plus a handful of concrete
probe inputs and the question it would ask if confirmed; both candidates are then actually run via
`env.exec_code` (new technique for our own algorithms — base64-embedded source, separate namespaces,
per-candidate and per-call `try/except` so a broken alternative can't take down the whole probe) and
the question is only asked if at least one input shows a real, reproducible output difference. The
DRAFT prompt also now names "a parameter the task text never mentions" as its own assumption
category, targeting the still-open `Mbpp/229`/`Mbpp/559` signature gap.

**3-run result** (same 30-task smoke set, seed 42, `openai/gpt-4.1-mini`, temperature 0.7):

| Run | TDS | nDCG | Pass@1 | Clarification rate |
|---|---|---|---|---|
| r1 | 0.6214 | 0.4667 | 63.33% | 46.67% |
| r2 | 0.6828 | 0.5000 | 70.00% | 50.00% |
| r3 | 0.6254 | 0.3333 | 63.33% | 33.33% |
| **Mean ± stdev** | **0.6432 ± 0.0344** | **0.4333 ± 0.0882** | **65.55% ± 3.85pp** | **43.33% ± 8.82pp** |

For reference: `LAASeR_Gate` (v1, 3 runs) TDS 0.6174 ± 0.0320, nDCG 0.9889 ± 0.0192, clarification
rate 100.00% ± 0.00pp. Champion `LAASeR_Repair`, now with a 4th matching historical run folded into
the same group by `scripts/compare_runs.py` (an earlier screening run from before the `-s42-r*`
labeling convention, same dataset tag): TDS 0.7160 ± 0.0200, nDCG 0.0500 ± 0.0334, clarification
rate 5.00% ± 3.34pp. `LAASeR_GateV2` does **not** beat the champion — all 3 of its runs sit below
even the champion's single lowest individual run (0.6974) — but it is a real improvement over v1 on
every axis that matters for the TDS/over-asking problem: TDS +0.026, and most importantly
clarification rate **100.00% → 43.33%**, more than halved, while nDCG (0.4333) stays far above the
champion's 0.0500.

**Mechanism check**, same discipline as every prior challenger — `clarification_history` for
`Mbpp/26, 229, 559, 759, 143` across all 3 runs:

- `Mbpp/26`, `Mbpp/229`, `Mbpp/143`, `Mbpp/759`: **never asked in any of the 3 runs** — the
  execution check consistently found no confirmed divergence (or the ALT+PROBE call itself said
  `DONE`) and correctly suppressed the question. This is the mechanism working as designed: these
  are exactly the kind of "the model feels a little unsure but it wouldn't change the output on the
  inputs it tried" cases v1's self-judged gate couldn't tell apart from a real ambiguity. The cost
  is that these 4 tasks still fail — correctly not asking doesn't make the underlying ambiguity
  resolve itself, and 3 of the 4 (`Mbpp/26`, `143`, `759`) have no stated examples in the prompt
  text for *any* mechanism (execution-grounded or not) to probe against; only asking (and getting a
  good answer) was ever going to fix them.
- `Mbpp/559`: asked in **all 3 runs**, every time about the empty-list edge case (not the actual
  missing-parameter root cause from `docs/failure-analysis.md`), confirmed by a genuine divergence
  each time, and still fails every time — same pattern as challenger #5: the execution check is
  working exactly as intended (it only asked because the two candidates really did disagree on
  `max_sub_array_sum([])`), it just isn't the question that would have fixed this specific task.
- **Signature/arity hypothesis: still unsolved.** `Mbpp/229` never asked in any run, despite the
  DRAFT prompt now explicitly naming "a parameter the text never mentions" as an assumption
  category. The self-reported assumptions apparently still don't surface it as a candidate often
  enough for the ALT+PROBE step to ever pick it, so the execution check never gets a chance to test
  it either — the blind spot is one step upstream of where this challenger intervenes.

**Net task-level diff** (r3 vs. the champion's matched smoke-42 run): `LAASeR_GateV2` newly loses
`Mbpp/251, Mbpp/755, Mbpp/90, HumanEval/154` (all four pass under the champion) and newly gains
`HumanEval/108` — net -3, smaller than v1's net -4 but still a net loss on this sample.

**Cost note**: `env.exec_code` calls are not metered in `prompt_cost`/`clarification_cost` (confirmed
by reading `clarify/env.py`), so the reported `avg_cost_usd` for this version undercounts its real
compute cost relative to the champion and even relative to v1 — treat the dollar figures in
`results/internal_leaderboard.md` as LLM-token cost only, not total compute.

**Verdict**: `LAASeR_GateV2` does **not** beat the champion — kept, not deleted, logged as experiment
six. Real, measured progress on the exact mechanism the team flagged as broken in challenger #5
(over-asking cut by more than half, nDCG preserved far above the champion's), but the gap to the
champion (0.073 TDS) still exceeds the combined stdev and holds across all 3 runs, and the
signature/arity hypothesis the user specifically asked about remains open — it needs an intervention
further upstream (making the DRAFT step's self-report actually surface "extra parameter" as a
candidate more reliably) rather than a better verification step once it's already there. Natural
next directions, not yet attempted: (a) tighten the DIVERGE check further by requiring the probe
inputs to look like something the hidden tests would plausibly cover rather than any input that
happens to disagree, since several of the task-level regressions are plausibly "real but
hidden-test-irrelevant" divergences; (b) attack the signature gap at the DRAFT step directly (e.g.
an explicit AST-based self-check of the drafted candidate's own parameter count against the task
text, rather than relying on the model's free-text self-report to mention it).
