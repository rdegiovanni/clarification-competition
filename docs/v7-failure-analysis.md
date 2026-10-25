# LAASeR_PinpointSMT v7: where the failures come from (2026-10-15)

File analysed: `clarify/algorithms/laaser_pinpoint_smt_3.py` (v7: `question_samples=3`,
`candidates=3`, `checklist=True`, `question_source="audit"`, `tolerate_extra_args=False`).
Smoke set: `--smoke-source val --smoke-size 70 --smoke-seed 42`, `openai/gpt-4.1-mini`,
temperature 0.7.

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
