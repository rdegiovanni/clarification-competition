# LAASeR — team runbook

Internal guide for running the evaluation pipeline (smoke tests, full splits,
and reports) on any algorithm file in `clarify/algorithms/`. For scoring
rules, competition constraints, and the decision log, see `CLAUDE.md`. This
file is just "how do I run it."

## One-time setup

```bash
uv sync --all-extras --dev
```

Also required:
- **Docker Desktop running** — `evaluate_responses.py` scores candidates
  inside a sandboxed `ganler/evalplus` container, pulled automatically on
  first use.
- A `.env` file at the repo root (gitignored — never commit it) with your
  LLM gateway credentials, referenced by name, not by literal value:
  ```
  ANTHROPIC_API_KEY=$ANTHROPIC_AUTH_TOKEN
  ANTHROPIC_API_BASE=$ANTHROPIC_BASE_URL
  ```
  `scripts/evaluate.sh` sources `.env` automatically before running anything.

## Running a smoke test

```bash
scripts/evaluate.sh --clarify-py clarify/algorithms/<YourAlgorithm>.py \
  --language-model openai/gpt-4.1-mini
```

That's the whole pipeline in one command:

1. **Unit tests** — `uv run python -m unittest discover -s tests -v` (offline,
   no Docker/network).
2. **Build a smoke dataset** — `scripts/make_smoke_dataset.py` draws a random
   sample spread across benchmark classes (default: `Mbpp` + `HumanEval`,
   60 tasks total, split evenly) into `results/runs/<run>/smoke_data/`.
3. **Generate** — runs your algorithm against each class's sample via
   `generate_responses.py` (once per class — the organizer loaders only
   accept one benchmark class per dataset file).
4. **Evaluate** — scores each class's generations via `evaluate_responses.py`
   (official TDS/nDCG/Pass@1/etc.), merges the per-class results.
5. **Report** — `scripts/make_report.py` writes a Markdown report, appends a
   row to `results/history.csv`, and updates `results/latest_report.md`.

Every run is self-contained under `results/runs/<timestamp>_<label>/`:
`unittest.log`, `generate.log`, `evaluate.log`, `generate.jsonl`,
`results.jsonl`, `report.md`, plus the `smoke_data/` sample used.

### Smoke-test flags

| Flag | Default | What it does |
|---|---|---|
| `--smoke-size N` | `60` | Total tasks for the run, split evenly across `--smoke-classes` |
| `--smoke-classes LIST` | `Mbpp,HumanEval` | Comma-separated benchmark classes to sample from |
| `--smoke-random` | off | Ignore `--smoke-size`; randomly pick 30 or 60 tasks for this run |
| `--smoke-seed N` | unset | Seed the sample for a reproducible smoke set (default: fresh random sample every run) |

These only apply when neither `--split` nor `--dataset-path` is given — that's
the default "smoke" mode. Examples:

```bash
# default: 60 tasks, 30 Mbpp + 30 HumanEval
scripts/evaluate.sh --clarify-py clarify/algorithms/LAASeRAlgorithm.py

# bigger/smaller smoke set
scripts/evaluate.sh --clarify-py clarify/algorithms/LAASeRAlgorithm.py --smoke-size 100

# only one class
scripts/evaluate.sh --clarify-py clarify/algorithms/LAASeRAlgorithm.py --smoke-classes Mbpp

# let the script flip a coin between 30 and 60 tasks (useful for quick noise checks)
scripts/evaluate.sh --clarify-py clarify/algorithms/LAASeRAlgorithm.py --smoke-random

# reproducible sample (same 60 tasks every time)
scripts/evaluate.sh --clarify-py clarify/algorithms/LAASeRAlgorithm.py --smoke-seed 42
```

## Running a full split instead of a smoke test

```bash
scripts/evaluate.sh --clarify-py clarify/algorithms/<YourAlgorithm>.py \
  --language-model openai/gpt-4.1-mini --split val
```

`--split train|val` (or `--dataset-path PATH` for a single custom file, one
class only) switches off smoke mode entirely and runs the original
single-call generate/evaluate path against the full split (the official
validation split is 770 tasks — expect a long run).

## Other flags (apply in both modes)

| Flag | Default | What it does |
|---|---|---|
| `--clarify-py PATH` | `clarify/algorithms/LAASeRAlgorithm.py` | Algorithm file to evaluate |
| `--language-model MODEL` | `$LANGUAGE_MODEL` env var, or `anthropic/claude-sonnet-5` | LiteLLM model string — use `openai/gpt-4.1-mini` to match the public leaderboard |
| `--max-workers N` | `4` | Parallel workers for generation/evaluation |
| `--temperature T` | SDK default (0.7) | Sampling temperature forwarded to `generate_responses.py` |
| `--label NAME` | derived from `--clarify-py` | Suffix for the run folder under `results/runs/` |
| `--extra-gen-args "..."` | — | Extra args forwarded verbatim to `generate_responses.py` |

Run `scripts/evaluate.sh --help` any time for the live flag list.

## Where results end up

- `results/runs/<timestamp>_<label>/report.md` — full report for that run.
- `results/latest_report.md` — always the most recent run, any algorithm.
- `results/history.csv` — one row per run ever executed; this is the actual
  team-wide progress log (TDS/nDCG/Pass@1/etc. over time, keyed by
  algorithm/model/split/dataset). Compare multiple rows before concluding a
  change helped or hurt — `temperature=0.7` means single-run deltas include
  sampling noise.

## Running pieces individually

```bash
# offline unit tests only
uv run python -m unittest discover -s tests -v

# just build a smoke dataset (inspect it, reuse it, etc.)
uv run python scripts/make_smoke_dataset.py --n 60 --classes Mbpp,HumanEval --out-dir /tmp/my_smoke

# repo/submission validation (same checks CI runs)
uv run python scripts/validate_repository.py
uvx ruff check .
```
