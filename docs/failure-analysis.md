# Failure analysis (Fase 1)

Dev-tooling doc (not part of the submission). Built from the 30-task two-class smoke set
(`smoke(classes=Mbpp,HumanEval,n=30)`, seed 42, `openai/gpt-4.1-mini`, `temperature=0.7`), 3 runs
each for `LAASeR_Repair`, `LAASeRAlgorithm`, `LAASeR3Algorithm`, `LLMClarification` (organizer
baseline). Raw data: `results/runs/20261009T13*`, aggregated in `results/internal_leaderboard.md`
(regenerate with `uv run python scripts/compare_runs.py --label-filter s42`).

A tooling bug was found and fixed while building this doc: `scripts/compare_runs.py`'s
universal-failure/oracle diagnostics compared a task id against algorithm-label keys
(`tid in matrix.get(tid, {})`, always false) instead of checking whether each algorithm label was
present for that task (`lbl in matrix.get(tid, {})`). Before the fix it silently reported
"0/30 universal failures" and "0% oracle rate" on data that visibly contained several all-zero
rows. Fixed in the same file; not an organizer-owned file, so no separate PR needed.

## Universal failures: 6/30 (fail for every one of the 4 algorithms)

`HumanEval/139, Mbpp/143, Mbpp/229, Mbpp/26, Mbpp/559, Mbpp/759`. Oracle rate (solved by at least
one of the 4): 24/30 (80%). These 6 are the real floor — no amount of tuning *our* algorithm's
ask/repair logic will fix them unless the fix addresses the actual root cause below, since even
the simplest one-shot baseline (`LLMClarification`) and the simplest of our own algorithms
(`LAASeRAlgorithm`, no repair loop at all) fail them identically.

### `HumanEval/139` (`special_factorial`) — root cause (e): sandbox infra, not fixable by us, with a sharp operational trap

Candidate logic is correct for the stated examples. The underlying cause is CPython 3.11+'s
int-to-str conversion digit limit (4300 by default) being tripped by a factorial-sized ground
truth value, and it bites in **two different places**, confirmed by direct observation of both:

1. **Inside the Docker-sandboxed scoring container's own fresh Python interpreter**
   (`/app/temp_script.py`) — this is what every one of our committed runs hit: a clean per-task
   failure (`SyntaxError: Exceeds the limit...`), everything else in the batch unaffected. All 4
   algorithms fail this task identically, including the simplest one-shot baseline — strong
   evidence it's organizer-owned sandbox infra, not an algorithm bug.
2. **Host-side, in `clarify/runtime.py`'s `_construct_tests` (`str(value)` on the ground-truth
   `results` list, line ~158)**, called from `evaluate_responses.py` *before* anything is handed to
   Docker. This path raises the exact same `ValueError`, but **unhandled, inside a
   `ProcessPoolExecutor` worker** — it propagates all the way up and kills the entire
   `evaluate_responses.py` invocation, discarding every other task's result in that batch, not
   just this one. Reproduced directly: a screening run for `laaser_repair_v2.py` launched without
   `PYTHONINTMAXSTRDIGITS=0` exported on the host crashed after only 12/30 tasks with this exact
   traceback; the identical run with that env var set completed cleanly (task still fails
   individually, batch survives).

Practical rule going forward, for every `scripts/evaluate.sh` invocation we run ourselves:
**always export `PYTHONINTMAXSTRDIGITS=0` in the shell before launching it.** This doesn't fix the
task (the Docker container still fails it independently, since it doesn't inherit host env either
way) — it only prevents one unlucky task from silently destroying an entire batch's results. Noted
in `CLAUDE.md`'s Known SDK quirks section. We cannot touch `clarify/runtime.py` or the Docker
image, so the task itself is out of scope for any Fase 3 fix.

### `Mbpp/26` (`check_k_elements`) — root cause (b)+(a): asked, but resolved the wrong ambiguity

Prompt: *"Write a function to check if the given tuple list has all k elements."* `LAASeR_Repair`
**did** ask: *"what is the parameter k, and what elements should be checked against the tuples in
the list?"* → answer: *"k is an integer representing the exact number of elements each tuple
should have; check that every tuple contains exactly k elements."* That's a plausible reading of
the prompt, but the hidden test's real semantics is homogeneity, not arity:
`check_k_elements([(4,4),(4,4,4),(4,4),(4,4,4,4),(4,)], 4) == True` — every tuple here has a
*different* length, so "exactly k elements per tuple" is false for most of them; what's actually
being checked is that every *element value* in every tuple equals `k` (all 4s). The algorithm did
ask a question, got a confidently-stated answer, and still landed on the wrong semantic model —
this is a case where asking alone isn't enough; the question itself needs to probe deeper (e.g.
ask for a concrete pass/fail example) rather than accept a plausible-sounding abstract definition.
Self-verification against the bare prompt would not help — there are no worked examples in the
prompt text to test a candidate against.

### `Mbpp/229` (`re_arrange_array`) and `Mbpp/559` (`max_sub_array_sum`) — root cause (b): classic MBPP implicit-arity signature, never asked about

Neither algorithm asked (`clarification_history: []`) despite `need_clarification: True`. Both fail
identically: `TypeError: <fn>() takes 1 positional argument but 2 were given`. Hidden tests call
`re_arrange_array([-1,2,-3,4,5,6,-7,8,9], 9)` and `max_sub_array_sum(arr, n)` — a second, redundant
"array length" parameter that is a well-known MBPP convention (the original dataset's reference
solutions take `(arr, n)` even though `n == len(arr)` always) but is **never implied by the bare
one-line prompt text**, since no function stub/signature is shown. This is not noise — it's the
same failure signature in two different stable-failing tasks, both from the same "no stub shown,
model assumes a single-argument signature" root cause. This is the single strongest, most
actionable, multi-instance pattern in this analysis: an algorithm that explicitly checks whether
the prompt specifies a full function signature (vs. just a name) and asks a cheap, concrete
"what are the function's parameters?" question when it doesn't would plausibly fix both of these
without any self-verification machinery.

### `Mbpp/143` (`find_lists`) — root cause (a)+(d): the original (unperturbed) MBPP task itself is ambiguous

Confirmed by checking `data/mbpp/mbpp_original.jsonl` directly (not a competition-induced
perturbation): `test_cases` include
`find_lists(([9, 8, 7, 6, 5, 4, 3, 2, 1])) == 1` — note the single parens are *not* a tuple (no
comma), so this call passes one bare list, and the "correct" semantic is "if the single argument
is itself a list rather than a tuple-of-lists, that counts as 1". No reasonable reading of
*"find number of lists present in the given tuple"* predicts this edge case; it is a known
peculiarity of the original (non-perturbed) MBPP-143 reference tests, not something introduced by
this competition's prompt-perturbation pipeline. The one-line prompt gives no worked examples, so
self-verification against stated examples would not help either — this is a case where only
*asking for an example* ("can you show what one valid input/output pair looks like?") would have a
chance of surfacing the quirk.

### `Mbpp/759` (`is_decimal`) — root cause (a): candidate's reading of "decimal" admits negatives, the hidden ground truth doesn't

Prompt: *"check a decimal with a precision of 2."* Candidate accepts a negative sign
(`integer_part.lstrip('-').isdigit()`); hidden test:
`is_decimal('-123.11') == False` (expected `False`, candidate returns `True`). The likely original
MBPP reference solution is a regex like `^[0-9]+\.[0-9]{1,2}$` (no leading `-` branch), i.e. the
task's informal notion of "decimal" implicitly excludes negative numbers in the reference
implementation, which the one-line prompt text does not state or imply either way. No worked
examples are given, so again self-verification against the prompt's own text would not catch this
specific edge case — the fix would have to come from asking (e.g. "should negative numbers be
considered valid decimals here?").

## Noise-only failures (fail in exactly 1 of 3 `LAASeR_Repair` runs — not stable, not analyzed per-task in depth)

`Mbpp/755` (r1 only), `HumanEval/154` (r2 only), `HumanEval/108` (r3 only). These flip between pass
and fail across identically-configured runs purely from `temperature=0.7` sampling — consistent
with `CLAUDE.md`'s standing caveat that single-run deltas aren't signal. Not treated as evidence
for or against any hypothesis below.

## A case worth separating from the above: `HumanEval/55` shows self-verification's real limit

`HumanEval/55` (`fib`) is **not** a universal failure (`LAASeR3Algorithm` solves it; `LAASeRAlgorithm`,
`LAASeR_Repair`, and the direct baseline don't), but it's instructive: the prompt has 3 real
doctests (`fib(10)==55`, `fib(1)==1`, `fib(8)==21`), the candidate satisfies all 3, and still fails
the hidden test with `ValueError: n must be a positive integer` — the candidate added input
validation that happens to reject whatever edge-case input (likely `n<=0`) the hidden test actually
exercises, which none of the 3 given doctests cover. **This is important for scoping Fase 3's
self-verification idea honestly**: running a candidate against the examples already stated in the
prompt only catches bugs the statement's own examples would reveal. It would not have caught this
one. Self-verification is a real, cheap win for tasks whose stated examples *do* cover the
disagreement (and MBPP's bare prompts without examples get no benefit from it at all, since there's
nothing to run the candidate against) — not a general correctness guarantee.

## Cross-algorithm architecture notes (from reading the 3 organizer-provided SDK baselines)

- `clarify/baselines/direct.py` (`LLMClarification`, 46 lines): single LLM call, no repair loop; on
  a malformed response it calls `env.ask_human(response)` passing the raw malformed text itself as
  the "question" (not a real clarifying question) and retries once. Simplest possible baseline;
  explains its 0.0000 nDCG on the public leaderboard (it never asks a *real* question) despite a
  respectable Pass@1.
- `clarify/baselines/okanagan.py` (`Okanagan`, 144 lines): generates a seed candidate **first**,
  then always asks a judge-LLM whether a clarifying question is warranted given that candidate
  (`"NO_QUESTIONS"` means return as-is). Architectural precedent for a "gate the question on a
  judgment about the already-drafted candidate" family, distinct from our "decide before writing
  any code" structure.
- `clarify/baselines/clarifygpt.py` (`ClarifyGPT`, 210 lines): generates a seed candidate, has the
  model write *self-tests from the candidate itself*, validates those self-tests pass against the
  candidate via `env.exec_code` (`f'{candidate}\n{test_cases}\nprint("TEST SUCCESS")'`), then
  generates up to 24 alternative candidates and asks a question only if an alternative disagrees
  with the seed on its own self-tests. Direct precedent for a disagreement-sampling self-check,
  and the concrete `env.exec_code` convention to reuse — but 24 extra LLM calls per task is
  expensive; any variant we build on this pattern should use a much smaller sample (e.g. k=3) to
  respect avg-cost tracking.
- `clarify/algorithms/LAASeRAlgorithm.py` (ours, oldest/simplest): its `READY_TO_CODE_TEMPLATE`
  already has a *stronger* entry-point-override paragraph than `LAASeR_Repair.py` /
  `laaser_repair_v2.py` do ("the hidden tests call the function `{entry_point}` by that exact name,
  so any other name fails every test regardless of whether the logic is correct" vs. the weaker
  one-liner in `LAASeR_Repair.py`). Not yet measured in isolation — flagged as a small, separately
  testable Fase 3 candidate, since the signature-ambiguity failures above (`Mbpp/229`/`Mbpp/559`)
  show the model already struggles to trust what the prompt text implies about a function's
  interface; a stronger explicit warning about the entry point name might generalize to a stronger
  warning about not trusting the prompt's implied arity either.

## Prioritized hypothesis list for Fase 3

1. **(Highest confidence, 2 confirmed instances)** Ask a cheap, concrete question about the
   function's exact parameters/signature whenever the prompt gives no stub and the task looks like
   it could need more than the arguments explicitly named in the prose (targets `Mbpp/229`,
   `Mbpp/559`, and plausibly other MBPP tasks sharing the same `(arr, n)`-style convention gap).
   Low cost (one extra question, same budget envelope the SDK already allows), high evidence.
2. **(Confirmed cap, high value where it applies)** Self-verification: generate 2-3 alternative
   candidates (ClarifyGPT-style, but k=3 not 24 for cost) and check them against *examples already
   present in the prompt text* (HumanEval doctests mostly; MBPP bare prompts rarely have any).
   Honest scope per `HumanEval/55`: this only catches disagreements the stated examples actually
   expose — it is not a substitute for asking when there are no examples to check against at all
   (most of the universal MBPP failures above have none).
3. **(Medium confidence, needs its own measurement)** Strengthen the entry-point/signature-trust
   warning in the generation prompt (closing the gap between `LAASeRAlgorithm.py`'s stronger
   wording and `LAASeR_Repair.py`'s weaker one), as a small standalone change, isolated and
   measured on its own before bundling with anything else.
4. **(Lower priority — infra, not ours to fix)** `HumanEval/139`-style sandbox digit-limit failures:
   document, don't attempt to fix; confirmed universal across all 4 algorithms we have data for.
5. **(Speculative, not yet evidenced)** For tasks like `Mbpp/26` where a question *was* asked but
   still resolved to the wrong semantic, consider whether the clarifying question itself should
   request a concrete input/output example rather than an abstract definition — only one instance
   observed so far, worth watching for a second instance before investing in a dedicated fix.

## 2026-10-10 refresh — statistical taxonomy across champion + both Gate challengers (315 rows)

Built `scripts/analyze_failures.py` (dev tooling) to classify every failing row across the smoke-42
runs of `LAASeR_Repair` (champion, 4 runs), `LAASeR_Gate` (v1, 3 runs), and `LAASeR_GateV2` (3 runs)
by root-cause signature read from `test_result`, cross-tabbed against whether a clarification was
asked. Aggregate (104 failures across 315 rows, 67.0% overall pass rate):

| Category | Count | Unique tasks | Asked a question |
|---|---|---|---|
| code ran, wrong output (no exception) | 55 | 18 | 30/55 |
| signature/arity mismatch (TypeError, wrong arg count) | 22 | 4 | 9/22 |
| runtime error: ValueError | 11 | 2 | 3/11 |
| infra: sandbox digit limit (unfixable) | 9 | 1 | 4/9 |
| runtime error: AttributeError | 6 | 1 | 3/6 |
| runtime error: IndexError | 1 | 1 | 0/1 |

Two findings worth acting on:

1. **The signature/arity bug class is bigger than the 2 tasks we'd previously confirmed.** The
   champion's wider 4-run sample surfaces it on `Mbpp/617` and `Mbpp/888` too, not just `Mbpp/229`/
   `Mbpp/559` — same `(arr, n)`-style redundant-length-argument convention, 4 distinct tasks now
   confirmed, 22 total occurrences. It is also the category where `LAASeR_GateV2`'s single-hypothesis
   bottleneck shows up most clearly in the numbers: it asks about this class only 2/6 times vs. v1's
   6/6 — rarer, not more frequent, because v2 only tests the *one* assumption its DRAFT step
   self-selects, and that selection apparently picks something else more often than not.
2. **`Mbpp/90` is a real regression introduced by our own prompt change, not an inherent ambiguity.**
   The champion passes it in every run (`def len_log(words): return max(len(word) for word in
   words) if words else 0` — correctly guesses the hidden test passes an already-tokenized list of
   words). Both `LAASeR_Gate` and `LAASeR_GateV2` fail it in 100% of their runs (6/6 combined), every
   time with the *same* bug: the candidate assumes `s` is a raw string and calls `s.split()`,
   raising `AttributeError: 'list' object has no attribute 'split'`. The task prompt
   ("find the length of the longest word") gives no signal either way about whether the input is a
   sentence-string or a pre-split list — this is the exact same unnamed-parameter-*type* ambiguity
   as the `(arr, n)` unnamed-parameter-*count* class above, just never named as its own category.
   The clean 0%-vs-100% split (not a mix) across runs is the same side-effect pattern already
   documented for challengers #2–#4 in `REPORT.md`: adding instruction text to the generation prompt
   (here, our `ASSUMPTIONS:` section) measurably shifts behavior on tasks it was never aimed at.

**Priority update for the next Fase 3 attempt**: the single highest-leverage, best-evidenced fix is
no longer a new wording tweak — it's fixing the *discovery* bottleneck itself. `LAASeR_GateV2`'s
execution-verification mechanism (confirmed working: cuts over-asking by more than half, nDCG stays
high) is bottlenecked by testing only the one assumption its DRAFT step happens to self-select.
Testing *several* self-reported assumptions per task (closer to the full CONTRA pipeline's
"broad discovery → qualify many in parallel → select one" rather than our "pick one, then verify
it" shortcut) should recover more of the signature/arity class without giving up the over-asking
win, since each candidate still has to pass the same execution check before it can be asked.
