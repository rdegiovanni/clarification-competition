# LAASeR_PinpointSMT v7: where the failures come from (2026-10-15)

File analysed: `clarify/algorithms/laaser_pinpoint_smt_3.py` (v7: `question_samples=3`,
`candidates=3`, `checklist=True`, `question_source="audit"`, `tolerate_extra_args=False`).
Smoke set: `--smoke-source val --smoke-size 70 --smoke-seed 42`, `openai/gpt-4.1-mini`,
temperature 0.7.

> [!IMPORTANT]
> **Key finding (2026-10-26): the remaining failures are mostly not fixable by better
> formalization.** Per val run (~210 failures, mean of four runs):
>
> - **17 fail on unperturbed tasks**: the coder's own error rate, a floor no clarification
>   removes.
> - **64% of the failures are tasks with 2+ hidden requirements**: with one clarification turn,
>   at least one requirement never reaches the coder, and formalizing cannot recover information
>   that was never given.
> - **The largest single class, HumanEval `larbi_contradictory` (19 of 30 variants fail), has no
>   legitimate fix**: in 14 of them the code obeys an injected output-format statement ("return
>   the result as a string", "also return the sum") and returns `"0"`, `"2, 3, 1, 3"`,
>   `(True, 17)` or `"four"`. The perturbation also rewrote the type hints and the examples, so
>   text, signature and examples all agree on the wrong format; only the original benchmark
>   knows it is wrong. Ignoring it would target the benchmark, not the task (disqualified by
>   CONTRIBUTING.md).
> - Formalization acts only after the answer, where at most ~36 of ~210 failures could be
>   rescued (17%), below the ±10 tasks of noise of one val run. That is why every post-answer
>   layer measured here (resolver, spec rewrite, JSON contract, convention) tied.
>
> Details: "Update 2026-10-26: injected statements" at the end of this file.

## Runs

| Run | Config | TDS | Passed | nDCG | Clar. rate | Over-asking | Cost/task |
|---|---|---|---|---|---|---|---|
| `20261015T090215Z_smt-v6` | defaults (file possibly earlier edit) | 0.7007 | 51/70 | 0.929 | | | $0.0021 |
| `20261015T091616Z_smt-v6` | defaults | 0.6190 | 45/70 | 0.857 | | | $0.0036 |
| `20261015T105256Z_v7-default-r1` | defaults | 0.6739 | 49/70 | 0.886 | 95.7% | 87.5% | $0.0035 |
| `20261015T105301Z_v7-off-r1` | `--question_samples 1 --candidates 1` | 0.6327 | 46/70 | 0.900 | 95.7% | 81.3% | $0.0018 |

Same code, same 70 prompts: 51, 45 and 49 passed. A 6-task spread is sampling noise, so the
3-task gain of the defaults over the options-off run is not yet evidence.

## Finding 1: asking is not where the tasks are lost

`v7-default-r1`, by (needs clarification, asked, passed):

| needs clarification | asked | passed | tasks |
|---|---|---|---|
| no | no | yes | 2 |
| no | yes | yes | 14 |
| yes | no | yes | 1 |
| yes | yes | yes | 32 |
| yes | yes | **no** | **21** |

- The 87.5% over-asking rate looks alarming but costs almost nothing: all 16 tasks that did
  not need a question passed; the 14 needless questions only discount them from 1.0 to
  `log(10)/log(11) = 0.96`, about 0.008 TDS in total.
- The simulated user rated 62 of 67 replies QUALITY=3 (the best). The 21 lost tasks asked a
  question and got a good answer, and still failed.

## Finding 2: the 21 failures, by cause

1. **The hidden test passes arguments the task never declares** (to be handled later):
   Mbpp/229, /559, /371, /617 (`TypeError: takes 1 positional argument but 2 were given`);
   Mbpp/128 looks like the same class or a guessed argument order.
2. **Forced "known hard" tasks** (`KNOWN_HARD_TASKS` in `scripts/make_smoke_dataset.py`, mostly
   train-split tasks every algorithm fails): HumanEval/139 (crashes inside the sandbox on the
   int-to-str digit limit), Mbpp/143 (the test passes a list where the task says tuple),
   Mbpp/26, /759, plus /229, /559, /617 above. They count as failures for every variant and
   do not separate one version from another.
3. **A real ambiguity was asked and answered, but the test checks a different one** (about
   10 tasks, the main cause). Mbpp/719 asked whole-string vs. substring match; the test wants
   the literal `'Found a match!'`. Mbpp/349 asked which characters are allowed; the test wants
   `"Yes"` instead of `True`. Mbpp/374 asked about duplicate permutations; the test wants a
   specific order. Also HumanEval/15, /98, /145, /6, /86, Mbpp/748, /81. With one
   clarification turn a question covers one fact, and here the hidden requirement was another.
4. **The answer leads away from the test**: Mbpp/368 got "concatenate the whole sequence n
   times" while the test expects `((1, 3), (1, 3), ...)`; Mbpp/619 asked a bundled question
   whose answer did not fix the output.

## Finding 3: the z3 layers almost never run

In `solve()`, the solver layers (`find_certificate`, `find_interpretation_conflict`, the
type-clash check) run only under `if coding or solver_first:`. With the default
`question_source="audit"` that means only when the audit decides to code without asking.
The audit asks in 95.7% of tasks, so the solver ran in about 3 of 70. A contradiction z3 could
prove (a statement against an example, two readings that return different values on a
concrete input) is discarded whenever the audit already has its own question, which is
almost always.

`question_source="solver"` replaces the audit's question with the solver's; its comment says
that has not paid off on smoke-70. An untested middle ground: add the solver's question as
one more candidate in the question choice instead of replacing or ignoring it.

## Next steps

1. Measure how many smoke tasks have a z3-detectable contradiction or reading conflict (the
   ceiling for the middle ground above), before implementing it.
2. Determinism: `decision_votes` (ASK/CODE by majority of sampled audits) and
   `question_choice="consensus"` (the medoid question, no extra sampled call) are implemented
   behind flags, defaults unchanged (`tests/test_laaser_pinpoint_smt_3.py`); being measured on
   the 22 tasks that flipped between past smoke runs, 3 runs each.
3. Extra arguments in hidden tests, separately.

## Notes on tooling found along the way

- The simulated user runs at temperature 0.0 (`clarify/env.py:121`), not 0.7: the same
  question gets essentially the same answer, so answer variance comes from our wording.
- `tests/test_laaser_pinpoint_smt.py` (61 tests) targets the committed
  `laaser_pinpoint_smt.py`, not v7, and fails one test (`checklist_shows_only_the_entries`)
  in every `evaluate.sh` run; against v7 it fails 28 (stale helper and backtick expectations).
- `scripts/repeat_task.sh`, `diff_runs_by_task.py`, `show_task.py` mentioned in the handoff
  do not exist in the repo; `scripts/run_task.sh` uses the unperturbed prompt, not the smoke
  variant.

## Update 2026-10-21: full validation, and what did not help

### v7 on the full validation split (770 tasks, `gpt-4.1-mini`)

| | v7 (`smt_3` defaults) | Pinpoint (3 runs) |
|---|---|---|
| TDS | **0.7108** | 0.6834, 0.7021, 0.7083 (mean 0.698) |
| Passed /768 | **567** | 545, 561, 566 |
| MBPP /418 | 289 | 263, 275, 282 |
| HumanEval /350 | 278 | 282, 286, 284 |
| nDCG | 0.870 | 0.836-0.865 |
| Cost/task | $0.0036 | $0.0010 |

Run `20261021T141943Z_v7-val-r1`. Above 0.70 and the best val run so far, but a single run that
only just beats Pinpoint's best (567 vs. 566): a second val run is needed before calling v7
better. v7 gains on MBPP (+16 over Pinpoint's mean) and loses on HumanEval (-6).

Smoke-70 is a poor proxy for the 0.70 target: it force-includes 8 "known hard" tasks (mostly
from the train split) that no variant passes, and one run varies by +-3 tasks.

### Failures by kind (v7 on val, 201 failures)

- Wrong value: 139.
- Signature: 52 (26%). 27 pass more arguments than the task declares (the trailing `n`; out of
  bounds by the rules, `tolerate_extra_args` stays off). 25 pass the arguments in another order
  or type, concentrated in 9 MBPP task ids without a signature in the prompt: Mbpp/433 (all 7
  variants: the text names "the number" before "the array", the test calls `(array, number)`),
  Mbpp/128 (6: the test calls `long_words(n, "a sentence")`), Mbpp/390 (4), ... In 13 of the 25
  the question was already about the arguments: the simulated user only reveals hidden
  requirements, and the argument order is often not one of them.
- Reading code from the console is misleading (handoff lesson 6.1): rich drops `[...]`, so
  `return [w for w in words if len(w) > n]` prints as `return`. Read `results.jsonl`.

### Variants measured on top of v7 (all kept behind flags, off by default)

| Variant | Where | Result | Verdict |
|---|---|---|---|
| `--decision_votes 5` | smoke-70 | 47/70 (v7: 51, 45, 49) | no gain in passes; halves flipping tasks on the flaky set; 1.6x cost |
| `--resolve_defects True` | smoke-70 | 39/70 | harmful: decisions taken from the perturbed text and examples propagate the perturbation (HumanEval/65 followed the edited example and stopped shifting) |
| combo (votes + consensus + spec rewrite + resolver) | smoke-70 | 47/70 | `consensus` picks bundled questions (QUALITY=1 5 -> 8) |
| `--question_target divergence`, free question | 23 tasks with 2+ hidden requirements | 11, 11 (v7: 13, 10, 10) | witnesses found in ~8/23 tasks, but the question drifted back to the audit's defect |
| same, question assembled around the witness | same 23 tasks | 12, 10 | witness questions reached the user (6, 10 tasks; QUALITY=3 mostly) and HumanEval/40, /6, /65, /82 passed in both runs; MBPP witnesses were edge cases unrelated to the hidden requirement |

The subset of tasks with 2+ hidden requirements comes from `scripts/make_multireq_set.py`,
which reads `data/clarifications.jsonl` only to count requirements and choose which tasks to
evaluate; no algorithm sees it.

### GeneticSpecClarification vs. v7 on smoke-70 (2026-10-21)

`clarify/algorithms/genetic_spec_improvement.py` (version of commit `9ebf797`, with Nagini
formalisation) on the same smoke set as v7 (`--smoke-source val --smoke-size 70 --smoke-seed
42`, `gpt-4.1-mini`), run `20261021T152053Z_genetic-val-s70-r1`. Earlier genetic runs used the
default smoke source (unperturbed tasks) and are not comparable.

| | genetic | v7 (3 runs) |
|---|---|---|
| TDS | **0.5955** | 0.7007, 0.6190, 0.6739 |
| Passed /70 | **43** | 51, 45, 49 |
| MBPP /39 | 21 | 26, 20, 24 |
| HumanEval /31 | 22 | 25, 25, 25 |
| nDCG | **0.671** | 0.857-0.929 |
| QUALITY=1 answers | **12** | 5-6 |
| Clarification rate | 84% | 96% |
| Cost/task | $0.0022 | $0.0035 |

By hidden requirements, the loss is mostly on tasks with 1 requirement (18 vs. 19-22), the ones
v7 nearly solves. No task v7 always fails is gained; 5 tasks v7 always passes are lost
(HumanEval/142, /65, /72, Mbpp/215, /388).

Cause: the question. The genetic algorithm's questions are broad or bundled ("What is the exact
format of the input, and what should the decoded output look like?", Mbpp/215) or ask for test
cases ("given the list [-1,-5,2,-1,-5], what is the expected transformed list?", HumanEval/142),
which the simulated user scores QUALITY=1 (ATOMICITY, LEAKAGE) and answers vaguely. v7's audit
forces a quoted phrase, competing readings and one fact. Its judge also skipped the question on
11 tasks it found correct. Next: the genetic algorithm with v7's question rules.

#### Follow-up: the genetic algorithm with v7's question rules and an entry-point alias

This variant lives in `clarify/algorithms/genetic_spec_improvement_v7q.py` (class
`GeneticSpecClarificationV7Q`); `genetic_spec_improvement.py` stays the team's original. The
`genetic-v7q-s70-r1` run had the question rules only, before the alias was added.

| Genetic | TDS | Passed | MBPP | HumanEval | nDCG | QUALITY=1 | NameError |
|---|---|---|---|---|---|---|---|
| original (`genetic-val-s70-r1`) | 0.5955 | 43 | 21 | 22 | 0.671 | 12 | 0 |
| + v7 question rules (`genetic-v7q-s70-r1`) | 0.5395 | 39 | 19 | 20 | 0.786 | 7 | 2 |
| + entry-point alias (`genetic-v7q-alias-s70-r1`) | 0.5675 | 41 | 19 | 22 | 0.743 | 7 | 0 |
| v7, 3 runs | 0.62-0.70 | 51, 45, 49 | 26, 20, 24 | 25, 25, 25 | 0.857-0.929 | 5-6 | 0 |

- v7's question rules (quoted phrase, competing readings, one fact, no test cases, no backticks)
  in `QUESTION_PROMPT` halve the QUALITY=1 answers and raise nDCG, gaining HumanEval/142, /72
  and Mbpp/388.
- The algorithm never checked the returned function's name: when the evolved description stops
  naming it, the model invents one (`def candidate(n)` for `sum_to_n`, `def items(val)` for
  `digits`) and every test fails with NameError. `alias_entry_point` appends `entry = <name>`;
  both tasks pass with it.
- All three genetic runs (43, 39, 41) stay below v7's worst run (45): with good answers, the
  remaining gap is the implementation after the answer (v7's coding prompt, sandbox check and
  voted candidates).

## Update 2026-10-23: failure origins, and three more variants that did not help

Public leaderboard (site, not the repo CSV): ZarutskiyClarifier leads with TDS 0.6697 (Pass@1
0.697, nDCG 0.926), then EDYClarifier 0.6610. v7 on val: 0.7108. Submission deadline Nov 6,
single track.

### Where v7 fails (val, 770 tasks; `scripts/classify_failures.py`)

MBPP 291/420 (69.3%), HumanEval 278/350 (79.4%).

| Origin | Fails | MBPP | HE | Asked | QUALITY=3 |
|---|---|---|---|---|---|
| wrong value | 122 (61%) | 65 | 57 | 121 | 106 |
| signature: argument order/type | 26 (13%) | 26 | 0 | 26 | 18 |
| wrong type | 17 (8.5%) | 5 | 12 | 17 | 14 |
| signature: extra arguments | 17 (8.5%) | 17 | 0 | 17 | 12 |
| signature: missing arguments | 10 (5%) | 9 | 1 | 10 | 7 |
| crash | 8 (4%) | 6 | 2 | 8 | 6 |
| no usable code | 1 | 1 | 0 | 1 | 1 |

Pass rate by hidden requirements: 0 → 94%, 1 → 83%, 2 → 61%, 3+ → 36%; 68% of the failures
are tasks with 2+ requirements. Even with 1 requirement elicited at QUALITY=3, 31 tasks fail:
the answer echoes the edited text (HumanEval/120: "the smallest values, as shown by example
1"; the test wants the largest) or the code obeys an oddity of the text (HumanEval/40, /72
return the string "False"). Wrong-type failures are the code obeying an added output demand
(HumanEval/57 `(True, 17)`, HumanEval/73 `'four'`). Returning the type of the signature's
return annotation would fix ~1 task: only 2 failures contradict an annotation, and in one the
annotation itself is edited.

Smoke-70 run `v7-s70-r4`: 48/70 (MBPP 59.0%, HumanEval 80.6%); 17 of its 22 failures also
failed in all three earlier v7 runs (7 are the forced hard tasks, 4 extra arguments).

### Variants (all behind flags, off by default)

| Variant | Where | Result | v7 on the same set |
|---|---|---|---|
| `--resolve_defects True --resolve_mode convention` (answer implications applied to every case, unconfirmed odd additions dropped, never the examples) | 23 tasks with 2+ requirements, 2 runs | 8, 11 | 13, 10, 10 |
| `--question_priority True --question_samples 5` (the judge ranks contradictions, return format, arguments, missing rules over edge inputs) | smoke-70 | 47/70, nDCG 0.800, QUALITY=1 8 | 45-51, nDCG 0.86-0.93, QUALITY=1 ~5 |
| `--use_solver False` (as if z3 were not installed) | smoke-70 | 45/70 | 45-51 |

Without z3: the two tasks lost against every v7 run (HumanEval/82, Mbpp/388) used the audit's
question in all five runs, never a z3 one; Mbpp/388 got "the exponent" instead of "the value"
this time. The z3 layers fired in 2-3 of 70 tasks per v7 run. v7 does not depend on z3: with
the optional import it behaves as `use_solver=False` where z3 is missing, so it can be
submitted without the library request (and z3 must stay out of `pyproject.toml`).

Three variants that decide or steer the unasked points explicitly (full resolver,
convention resolver, combo) all lost to the coder's silent guess; smoke-70 no longer separates
variants from v7 (every one this week stayed inside v7's 45-51). Next: a second v7 run on the
full validation split.

## Update 2026-10-23 (evening): second v7 run on the full validation split

| | val runs | TDS | mean | MBPP /418 | HumanEval /350 | cost/task |
|---|---|---|---|---|---|---|
| v7 (`laaser_pinpoint_smt_3.py`) | 2 | 0.7108, 0.6906 | **0.7007** (sd 0.014) | **289, 285** | 278, 267 | $0.0036 |
| Pinpoint (`laaser_pinpoint.py`) | 3 | 0.6834, 0.7021, 0.7083 | **0.6979** (sd 0.013) | 263, 275, 282 | **282, 286, 284** | $0.0010 |
| leader (ZarutskiyClarifier) | - | 0.6697 | | | | |

Run `20261023T153422Z_v7-val-r2`: TDS 0.6906, Pass@1 71.8%, nDCG 0.871; MBPP 68.1%, HumanEval
76.3%. The first run's 0.7108 was the high side of the noise: 101 of 768 tasks change outcome
between the two v7 runs.

- Overall, v7 and Pinpoint are tied (0.7007 vs. 0.6979, far inside one standard deviation), and
  v7 costs 3.5x more. Every one of the five val runs is above the leader's 0.6697.
- The split by benchmark is consistent across runs: v7 is better on MBPP (+14 tasks over
  Pinpoint's mean) and worse on HumanEval (-11.5). The layers v7 adds (data-structure checklist,
  sandbox check, voted candidates) help when the task is prose without a signature and hurt when
  it already gives the stub and docstring. Failure origins of the second run repeat the first:
  wrong value 64%, argument order/type 11%, extra arguments 7%, wrong type 7% (15 of 16 on
  HumanEval), missing arguments 6%.
- Next: choose the path by the shape of the task -- Pinpoint's behaviour when the prompt shows
  the `def` signature, full v7 when it is prose. If the effects add up, about 287 + 284 = 571/768
  (TDS ~0.715). It only depends on whether the task text shows a signature, never on task ids
  or hidden data. To be measured on val HumanEval first (MBPP is unchanged by it).

## Update 2026-10-24: argument order -- the data structure comes first

### Two results that did not help

- `stub_profile="pinpoint"` (v7's layers off when the prompt shows the `def` line) on val
  HumanEval: 277/350 (run `stubpp-valhe-r1`) vs. v7 278, 267 and Pinpoint 282, 286, 284. Against
  Pinpoint's always-passing stub tasks it lost 7 and won 4 that Pinpoint always fails, with the
  same kind of audit questions (one z3 question in 314): mostly sampling noise.
- `argument_convention` (a coding rule: "put the collection first, scalars after, unless the
  answer says otherwise") on val MBPP: 266 vs. 270 / 267 for v7 on the same 386 variants (32
  variants of run `argconv-valmbpp-r1` came back empty, cost $0, consecutive positions 328-359:
  an API outage, excluded). The rule reached every prompt, and the model ignored it: Mbpp/433
  stayed `check_greater(num, arr)` in 6 of 7 variants, following the order the text names them
  ("the entered number ... the given array"), while the tests call `check_greater(arr, number)`.

### The finding

In passing MBPP code from our runs, functions with one collection and one scalar parameter put
the collection first in 31 of 33 cases (94%). Debugging Mbpp/433 by hand in `chat.py`
reproduced the failure: the one question went to "strictly greater?", which the user confirms
without surprise, and the argument order was guessed from the text.

A prompt cannot enforce it, but a transformation can: `scripts/reorder_collection_first.py`
swaps the two parameters in the `def` line when the task shows no signature, the function has
exactly two parameters, and its body uses the first only as a scalar and the second as a
collection (the body refers to them by name, so nothing else changes). Applied offline to the
code of `v7-val-r2` and scored with the official tests (`results/whatif/`), same code with and
without the swap, no sampling:

| | passed (the 9 variants it touches) |
|---|---|
| v7 as generated | 1/9 |
| after the swap | 5/9 |

Mbpp/433 0/6 → 5/6; Mbpp/390 still fails (another defect); Mbpp/128 1 → 0, the one variant
where the user's answer had fixed the order ("an integer threshold as the first argument"). A
guard that keeps the order when the answer talks about it would make it +5 of 770 (about +0.005
TDS), at no LLM cost.

### Threats to validity

- **Ad hoc and possibly overfit.** The rule comes from our own validation runs, and the whole
  measured gain is three task ids (Mbpp/433, /390, /128), essentially one (Mbpp/433, all its
  variants). Nothing says the private test set has a task like it; on it the effect may be zero
  or negative.
- **Small sample behind the prior.** 33 functions, from runs on the same validation tasks, not
  an independent corpus; the 94% may not hold elsewhere, and counter-examples exist
  (Mbpp/28, /651, and Mbpp/128 itself, whose tests call `(n, sentence)`).
- **Close to fitting the oracle's style.** "Data structure first" is a common Python convention,
  not a task-specific rule, but we adopt it because MBPP's tests follow it. It never looks at
  task ids or hidden data; the team should still judge it against CONTRIBUTING.md's "target the
  task, not the oracle".
- **Heuristic roles.** Collection/scalar roles are read from the AST (iteration, indexing,
  `len()`, arithmetic, comparisons); ambiguous uses are left alone on purpose, which limits both
  the gain and the damage.

### reorder_arguments in the algorithm

`laaser_pinpoint_smt_3.py` now has `reorder_arguments` (off by default): `collection_first` on the
returned code of tasks without a signature, skipped when the user's answer talks about the
order (`ORDER_IN_ANSWER`, which keeps Mbpp/128's "first argument" variant). On the code of
`v7-val-r2` it changes exactly the same 9 variants as the offline script (770/770 identical).
Smoke-70 run `reorder-s70-r1`: 50/70, TDS 0.687 (v7: 51, 45, 49, 48); no task v7 always passes
was lost. Its own targets are barely in the smoke set (Mbpp/433 is not; Mbpp/390 was reordered
but fails for another reason), so the smoke only shows that it breaks nothing; the gain is the
offline measurement (+5 of 770 with the guard).

Asking about the argument order instead does not help: in 49 order/type failures over two val
runs, 21 questions were already about the arguments, 10 of them answered at QUALITY=1 (bundled),
and only 7 answers fixed an order; the 98 MBPP questions that mention the argument order pass
at 69%, the MBPP average. The order is rarely a hidden requirement.

## Update 2026-10-25: v7 + reorder_arguments on the full validation split

Run `20261024T152131Z_v7reorder-val-r1` (`--reorder_arguments True`): TDS 0.7033, Pass@1 73.1%,
nDCG 0.862, $0.0036/task, no empty results.

| | total /768 | MBPP /418 | HumanEval /350 |
|---|---|---|---|
| v7 + reorder | 561 | **293** | 268 |
| v7 (2 runs) | 567, 552 | 289, 285 | 278, 267 |
| Pinpoint (3 runs) | 545, 561, 566 | 263, 275, 282 | **282, 286, 284** |

- The reorder did what it was meant to: argument order/type failures 15 (v7: 26, 23), Mbpp/433
  4/7 (v7: 0, 0), and the best MBPP count so far.
- HumanEval, untouched by it, shows the gap is consistent: the v7 family 278, 267, 268 (mean
  271) vs. Pinpoint 282, 286, 284 (mean 284) over three runs each.
- Next: the hybrid -- Pinpoint's exact flow for tasks that show their signature, v7 + reorder
  for prose tasks; estimated about 293 + 284 = 577/768 (TDS ~0.72).

## Update 2026-10-25 (afternoon): the hybrid, and a Pinpoint control run

`stub_profile="pinpoint_exact"`: a task whose prompt shows its `def` line runs `pinpoint_run()`,
LAASeR_Pinpoint's `run()` line for line (`_check_code` / `_finalize` with `degenerate=False`,
which drops the only check v7 added to Pinpoint's validation); prose tasks keep v7 (+
`reorder_arguments`). A test feeds both algorithms the same scripted replies in four scenarios
and checks identical prompts, questions and code.

| val HumanEval (350) | total | with `def` (314) | date |
|---|---|---|---|
| hybrid (`hybrid-valhe-r1`) | 274 | 249 | 10-25 |
| Pinpoint, control rerun (`pinpoint-valhe-control`) | 280 | 253 | 10-25 |
| Pinpoint | 282, 286, 284 | 257, 258, 256 | 10-12 |
| `stub_profile="pinpoint"` | 277 | 251 | 10-23 |
| v7 / v7 + reorder | 278, 267, 268 | 250, 242, 244 | 10-21..24 |

- The control rules out a large date effect (the only SDK change since 10-12, `runtime.py` on
  10-22, cannot explain it either: v7's 10-21 run was already low). Pinpoint stays ahead on
  HumanEval: four runs, mean 283, vs. the v7 family's 271.
- One HumanEval run varies by about ±5 tasks: the same Pinpoint code scored 253 and 249 on the
  stub tasks today. The hybrid's 274 is likely a low draw of identical code, but one run cannot
  tell; a second run decides whether the hybrid (~293 MBPP + ~283 HumanEval ≈ 576/768) is worth it.

Second hybrid run (`hybrid-valhe-r2`): 279/350 (254 with `def`), level with today's Pinpoint
control (280 / 253). Two hybrid runs: mean 276.5 (251.5 with `def`); v7 family 271 (245.3);
Pinpoint 283 over four runs, 280 today. Part of the original gap was the date or luck of the
10-12 runs; on recent runs the hybrid gains about +5 HumanEval tasks over v7, at $0.0020 vs.
$0.0038 per task. Estimated full candidate: MBPP ~289-293 + HumanEval ~277 ≈ 566-570/768.

Hybrid on smoke-70 (`hybrid-s70-r1`, `--stub_profile pinpoint_exact --reorder_arguments True`):
48/70, TDS 0.6607, nDCG 0.829 (v7 + reorder 50/70, 0.6870; v7 45-51). HumanEval 27/31 (TDS
0.8415 on that class alone), MBPP 21/39. MBPP tasks show no `def` and take the v7 + reorder
path unchanged, so the MBPP dip is sampling noise; within the ±3 of one smoke run. The full val
run decides.

Full hybrid candidate on val (`hybrid-val-r1`): TDS 0.6796, 542/768 (MBPP 272, HumanEval 270),
nDCG 0.844, $0.0028/task; v7 + reorder 561 (293 + 268), v7 567 / 552. The MBPP path is the same
code as v7 + reorder (diff checked; no empty or zero-cost results), so 272 vs. 293 is sampling
noise: one full val run varies by about ±10 tasks on MBPP alone. HumanEval for the hybrid is
274 / 279 / 270 (mean 274) vs. the v7 family's 278 / 267 / 268: no measurable gain. The hybrid
is not worth the switch; v7 + reorder stays the candidate.

HumanEval/145 (`order_by_points`, 12 val variants) passes 6 / 5 / 4 / 5 of them per val run;
the failures sum the digits of `abs(x)` where the tests expect the sign on the first digit
(-12 -> -1 + 2), after a generic confirmation question. Of the 51 val variants that mention
digits, it is the only task failing on negative inputs.

### `number_reference`: digits of negative numbers (off by default)

One more entry in the audit's shape reference when the task mentions digits: "is the sign
ignored, or does it count with the first digit, e.g. -12 -> 1 + 2 or -1 + 2?". Ad hoc: built
from one task. Measured on the 7 val tasks that mention digits (`validation_digits.txt`, 72
variants, with `reorder_arguments`):

| Run | Passed / 72 | HumanEval/145 / 12 | Sign questions |
|---|---|---|---|
| `number_reference` r1 | 53 | 6 | 18 |
| `number_reference` r2 | 54 | 7 | 21 |
| control (same day) | 53 | 6 | 11 |
| earlier val runs (v7, v7, v7 + reorder) | 54 / 52 / 50 | 6 / 5 / 4 | - |

No gain. The question works (18 of 24 HumanEval/145 variants asked about the sign and got the
right answer), but most of those still failed on something else: a perturbation saying "return
the result as a string" that the coder followed, or a tie-break with `nums.index(x)` in the sort
key, which breaks the stable order for duplicates ([0, 0, -1, 1, 10, 1] -> 1 before 10). That
`.index()` pattern appears in 0-2 variants per val run, all of them HumanEval/145. The flag
stays off.

## Update 2026-10-26: injected statements (offline, no LLM)

`scripts/injected_statements.py` diffs every val variant against its unperturbed prompt
(`data/<class>/<class>_original.jsonl`) word by word (typos of a deleted word are not counted
as insertions) and names the perturbation file it comes from. Failures over four val runs
(v7 r1, v7 r2, v7 + reorder, hybrid), per run:

| Perturbation | Pass % | Failures per run |
|---|---|---|
| larbi_contradictory | 55.3 | 40.2 |
| larbi_ambiguous | 64.7 | 31.8 |
| larbi_incomplete | 67.0 | 29.0 |
| akli_lexical_vagueness | 75.0 | 22.2 |
| akli_syntax_and_formatting | 76.4 | 21.2 |
| akli_under-specification | 79.6 | 18.8 |
| original (unperturbed) | 81.4 | 16.8 |
| wu_* (seven files, 141 variants) | 58-100 | 32.7 |

- The unperturbed tasks fail 17 times per run: the coder's own error rate, the floor of what a
  better clarification can reach.
- Biggest bucket: HumanEval larbi_contradictory, ~19 failures per run out of 30 variants. 14 of
  them are a wrong type: the code obeys an injected format statement ("return the result as a
  string", "also return the sum", a success message) and returns `"0"`, `"2, 3, 1, 3"`,
  `(True, 17)` or `"four"` where the tests expect `0`, `[2, 3, 1, 3]`, `True`, `4`.
- There is no signal in the prompt against those statements: the perturbation also rewrote the
  type hints (`-> str` on `fizz_buzz`) and the examples (`== "four"`, `== "-1, -11, 1, -12, 11"`).
  Only the original benchmark knows the format is wrong. Ignoring a format the task states, its
  hints and its examples all agree on would target the benchmark rather than the task, which
  CONTRIBUTING.md disqualifies. The legitimate lever is the question (ask about the return
  format), but those variants inject 3-5 statements each and one question settles one.
- Returning a stringified value (`got` printed equal to `expected`, or a joined list): 7-10
  failures per run, all larbi_contradictory.

### `format_question`: ask about the return format (off by default)

When the task states a return format (`RETURN_FORMAT_STATEMENT`: "return ... as a string",
"must be an integer", ...), the audit is told to ask about the return value's type and format
with literal readings, and a sampled question about it wins over the judge's choice. Rationale:
in HumanEval larbi_contradictory, format questions passed 57% vs. 21% for other topics (four
val runs; selection-biased). Measured on the val variants that trip the trigger
(`scripts/make_format_set.py`; the dataset loader keeps one variant per task id, so 19 HumanEval
variants: 18 larbi_contradictory and one HumanEval/65):

| Run | Passed / 19 | Format questions |
|---|---|---|
| `format_question` r1 / r2 | 3 / 6 | 11 / 15 |
| control (same day) r1 / r2 | 5 / 1 | 10 / 8 |
| earlier val runs | 3 / 3 / 3 / 4 | - |

No measurable gain (the control alone spans 1-5). Why the format question still fails, checked
against the hidden requirements the simulated user receives (`data/clarifications.jsonl`;
read for analysis only, never by the algorithm):

1. **The question presupposes the injected format.** HumanEval/60: the user's hidden
   requirement says "return an integer value, not a string", but we asked "should the output be
   the string '15' (the sum) or '12345' (a concatenation)?": both readings were strings, so the
   user answered within them ("the string representation of the sum, such as '15'").
2. **The coder overrides a correct answer when the whole prompt says the opposite.**
   HumanEval/36: answer "as an integer"; the signature says `-> str`, the doctests `'0'` and the
   text "The output should be a string", and the code returned `str(...)` (after 80 lines of
   comments on "no loops / O(1)", which coding rule 2 says to ignore).
3. **The question is too narrow or goes elsewhere.** HumanEval/57: asked only about the False
   case, so the code still returned `(True, 17)`; about half of what the topic regex counts as
   format questions only mention the word "string".

Only HumanEval/66, whose variant has no hidden requirement on that point, got an answer made
up from the perturbed text. *Correction:* an earlier version of this section (commit
`d6ccf5b`) blamed the simulated user for confirming injected formats; the hidden requirements
show it knows the right format, and cases 1-3 are ours.

Example markers are not the cause either ("such as", "e.g.", "for example", "like"; four val
runs): QUALITY=3 answers with one pass 81.7% (104) vs. 74.4% without (2,551); prompts with one
70.6% (272) vs. 72.5% (2,808). In an answer the example is usually its most precise part
("-12 -> -1 + 2"); when an answer is wrong, the normative statement it illustrates is wrong.

**Lesson:** when the task states a format, the question has to contrast the stated format
with the natural type (`15` or `'15'`), and the coder has to follow the answer over the
signature, hints and examples: `format_question="contrast"`, below.

### `format_question="contrast"` (v2, off by default)

The audit rule asks for readings that set the stated format against the natural type ("the
integer 15 or the string '15'"); among the sampled questions, one that names a typed reading and
a string reading wins (`contrastive`); and the coder gets rule 5, "the answer overrides the task
text, the signature, the type hints and the examples". Same 19 variants:

| Run | Passed / 19 | Contrastive questions |
|---|---|---|
| v2 r1 / r2 | 5 / 5 | 12 / 15 |
| v1 r1 / r2 | 3 / 6 | 11 / 10 |
| control r1 / r2 | 5 / 1 | 10 / 8 |
| earlier val runs | 3 / 3 / 3 / 4 | - |

Mean 5.0 vs. 3.2 for the six control runs and 4.5 for v1: about +2 tasks per val run, not
significant on two runs. Where it fires, the mechanism works: HumanEval/60 failed in all six
earlier runs and passes in both (contrastive question, answer "integer", code follows it);
HumanEval/73 and /115 pass in both. The limit: the audit still asks about another injected
statement in about half of the variants (HumanEval/40 and /72 return `"False"` after questions
about "maintain order" and "1 or the sum"), and the preference can only choose among the sampled
questions.

### `format_question="dedicated"` (v3, off by default)

Everything of v2, plus: when the trigger fires and no sampled question is contrastive (or the
audit decided to code), one call (`FORMAT_QUESTION_TEMPLATE`, `format_type_question`) writes the
question about the return type, kept only if it is contrastive. Same 19 variants:

| Run | Passed / 19 | Contrastive questions | Answer "type, not a string" | Cost/task |
|---|---|---|---|---|
| v3 r1 / r2 | **7 / 7** | 19 / 19 | 7 / 5 | $0.0043 / $0.0048 |
| v2 r1 / r2 | 5 / 5 | 12 / 15 | 3 / 2 | $0.0052 / $0.0055 |
| v1 r1 / r2 | 3 / 6 | 11 / 10 | 2 / 2 | $0.0055 / $0.0056 |
| control, six runs | 5, 1, 3, 3, 3, 4 (mean 3.2) | 8-10 | 1 | ~$0.0050 |

Both v3 runs are above the best of six controls: +3.8 of 19. HumanEval/36, /60, /66, /73 and /115
pass in both. The remaining failures mostly have another hidden requirement (HumanEval/98 and
/131 now get the type right and fail on the logic; /57 and /145 have 4-5 requirements). On full
val the trigger fires on ~29 variants per run, so the expected gain is +3-4 tasks per run. Open
risk: HumanEval/65, whose original task does state "return the result as a string" (9 val
variants; the dataset loader kept one).

HumanEval/65 check (its original task does say "return the result as a string"; all 12 val
variants, one per dataset file because the loader keeps one variant per task id:
`results/format_sets/he65/run.sh`). The trigger fires on 9 of them; there v3 asks "the string
'21' or the integer 21?" and the user answers "string", which spends the question on a format
already right:

| Run | Passed / 12 |
|---|---|
| v3 r1 / r2 | 7 / 5 |
| control r1 / r2 | 7 / 8 |
| earlier val runs | 6 / 6 / 6 / 6 |

v3 mean 6.0 vs. 6.5 for six controls: within noise. Net expected on a val run: +3.8 on the 19
injected-format variants, about -0.5 on HumanEval/65, so about +3 tasks.

## Update 2026-10-26: the candidate on the full validation split

Candidate: v7 + `reorder_arguments` + `format_question="dedicated"` (`candidate-val-r1`).
TDS 0.6995, 558/768, nDCG 0.865, $0.0035/task. Split by whether the format trigger fires (the
only variants where the candidate's code differs from v7 + reorder):

| Run | Total | 29 trigger variants | other 739 | TDS |
|---|---|---|---|---|
| candidate r1 | 558 | **13** | 545 | 0.6995 |
| v7 + reorder | 561 | 8 | 553 | 0.7033 |
| v7 r1 / r2 | 567 / 552 | 7 / 9 | 560 / 543 | 0.7108 / 0.6906 |
| hybrid | 542 | 8 | 534 | 0.6796 |

On the 29 variants the candidate passes 13 vs. 7-9 (+5 over the mean of four runs). On the other
739 the code is the same as v7 + reorder (the hybrid differs on HumanEval), and the 545 vs. 553
is sampling noise: v7 r1 and r2 differ by 17 there on identical code. One run cannot separate the
totals; a second candidate run follows.

Second run (`candidate-val-r2`): TDS 0.7144, 570/768 (MBPP 290, HumanEval 280), nDCG 0.855,
$0.0035/task, the best val run so far.

| Run | Total | 29 trigger variants | other 739 | TDS |
|---|---|---|---|---|
| candidate r1 / r2 | 558 / 570 (mean 564) | 13 / 14 | 545 / 556 | 0.6995 / 0.7144 (mean 0.7070) |
| v7 + reorder | 561 | 8 | 553 | 0.7033 |
| v7 r1 / r2 | 567 / 552 (mean 559.5) | 7 / 9 | 560 / 543 | 0.7108 / 0.6906 (mean 0.7007) |

The +5 on the trigger variants repeats (13, 14 vs. 7-9 in four runs); the other 739 stay within
the v7 family's range. Candidate for the submission: v7 + `reorder_arguments` +
`format_question="dedicated"`.

Third run (`candidate-val-r3`): TDS 0.7070, 564/768 (MBPP 277, HumanEval 287, the best
HumanEval of any run, Pinpoint's 282-286 included), nDCG 0.860, $0.0035/task; trigger variants
11/29, other 739 553. Three runs: 558 / 570 / 564 (mean 564), TDS 0.6995 / 0.7144 / 0.7070 (mean
0.7070), trigger variants 13 / 14 / 11 vs. 7-9 before v3. All three above the public leader's
0.6697.

## Update 2026-10-28: LAASeR_Evolution and LAASeR_Contrastive_Specs on smoke-70

The two algorithms added in `44691c0` (both classes are named `LAASeR_Evolution`; the loader
works per file, but a submission needs distinct names). Evolution analyses the prompt, fixes it
or asks one question and rewrites it with the answer, then codes once. Contrastive_Specs adds a
loop that formalizes the prompt and the generated code and fixes the prompt until the two
specifications are judged equivalent. Both loops are bounded only by the budget and the
300 s timeout. smoke-70 (val, seed 42), one run each:

| Run | Passed | TDS | nDCG | MBPP | HumanEval | Cost/task |
|---|---|---|---|---|---|---|
| `LAASeR_Evolution` | 26/70 | 0.357 | 0.757 | 12/39 | 14/31 | $0.0017 |
| `LAASeR_Contrastive_Specs` | 27/70 | 0.372 | 0.743 | 12/39 | 15/31 | $0.0025 |
| v7 + reorder | 50/70 | 0.687 | 0.843 | 24/39 | 26/31 | $0.0037 |

No crashes or empty results (the "Exception" lines in the logs are prompt text, an
`Exsures(ValueError, ...)` contract rule). The questions are as good as v7's (QUALITY=3 in
52-53 of 70); the code is not: wrong value 23 vs. 12, extra or missing arguments 13 vs. 4.
Examples on tasks v7 passes: HumanEval/22 keeps `True`/`False` as integers, HumanEval/6
returns `[0]` for the empty string, HumanEval/115 and /86 miss a correct answer. v7 checks and
repairs the code after the answer (coding rules, sandbox calls, crash repair, candidates
compared by execution); these code once. The gap (24 tasks) does not justify a val run; the
prompt evolution idea would be better tested as a flag inside v7.
