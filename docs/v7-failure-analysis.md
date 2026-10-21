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
