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
public leaderboard (`GatedClarification` leads at 0.6410) — but that
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
