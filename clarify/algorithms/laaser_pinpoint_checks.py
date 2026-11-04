"""LAASeR_PinpointChecks: v7 (`laaser_pinpoint_smt_3.py`) with execution checks.

Three layers on top of v7 with the candidate's flags (reorder_arguments, format_question
"dedicated"), each behind its own flag:

1. example_checks: the examples the task states (doctests, `f(x) == y`) become checks.
2. answer_checks: after the user's answer, one call says which stated examples the answer (or
   the task text) contradicts -- those are dropped -- and which concrete calls the answer
   settles, with their results; those become checks too.
3. preclean: before anything else, one call deletes a sentence that cannot hold together with
   the rest of the task (an impossible limit, numbers demanded as strings, a closing clause that
   cancels the main statement). The edit is kept only if it is a pure deletion that leaves the
   signature, the examples and the function name untouched. Our own steps read the cleaned text;
   the user always sees the original.

With checks, v7's implementation and `finals` more written with the answer run in the sandbox;
a check that no implementation passes is dropped (the answer overrides it, or the perturbation
corrupted it); the one that passes most checks is kept (ties: v7's), then repaired up to
`check_repairs` times against the checks it fails, keeping a repair only if it passes more.

Dev tooling for now: it imports v7, so it is not a single-file submission yet.
"""

from __future__ import annotations

import ast
import difflib
import re
from typing import Any

from clarify.algorithms.laaser_pinpoint_smt_3 import (
    ANSWER_OVERRIDES_RULE,
    CODE_TEMPLATE,
    FALLBACK_TEMPLATE,
    ORDER_IN_ANSWER,
    LAASeR_PinpointSMT,
    _check_code,
    _fill,
    _finalize,
    _is_placeholder,
    _rules,
    call_adapter,
    collection_first,
    extract_examples,
    parse_probe_calls,
    run_candidates,
    same_value,
    shows_signature,
    verify_by_execution,
)
from clarify.env import ClarificationEnvironment, LimitsExceededException, TooManyQuestionException

MAX_CHECKS = 10
MAX_DELETED_SHARE = 0.4  # a cleanup that deletes more of the task is not a cleanup

PRECLEAN_TEMPLATE = """The Python task below, for the function `{entry_point}`, may have been edited so that one
sentence or clause no longer fits the rest: an implementation limit that cannot hold for this
task (constant time, no loops, no recursion where every element must be looked at), a demand to
return numbers or booleans as strings, a demand for a kind of input the rest of the task never
describes, or a closing clause ("but ...", "instead ...", "except that ...") that cancels what
the task says before it.

If you find exactly such a sentence or clause, copy the task with that text deleted and nothing
else changed: keep every other word, every example, the signature and the function name, and do
not add anything. Put the copy in one ```text block. Vague words, missing details and unusual but
consistent requirements are not such sentences. If there is nothing to delete, answer UNCHANGED.

Task:
<<<
{prompt}
>>>"""

CHECKS_TEMPLATE = """A Python task, a clarification from the user, and the examples the task states for
`{entry_point}`.

Task:
<<<
{prompt}
>>>
{clarification}
Stated examples:
{examples}

1. For every stated example, write one line `EXAMPLE <number>: KEEP` or `EXAMPLE <number>: DROP`.
   DROP an example when the user's answer contradicts it, or when it contradicts an explicit
   statement of the task text; KEEP it otherwise (also when it shows a detail the text omits).
2. Then write one line `{entry_point}(<arguments>) == <result>` for every concrete call whose
   result the user's answer states or confirms, including the example in the question if the
   answer confirms it. Python literals only. Write no such line if the answer settles no
   concrete call.
Write nothing else."""

REPAIR_TEMPLATE = """Implement the following Python task.

Task:
<<<
{prompt}
>>>
{clarification}
This implementation fails some checks that come from the task's own examples or from the user's
answer:
```python
{code}
```
Failed checks:
{failures}

Change the implementation so that it passes these checks (an example can show a detail the text
leaves implicit) and keep everything the checks do not concern. Where a check contradicts the
user's answer, follow the answer.
{rules}"""

TEXT_BLOCK = re.compile(r"```(?:text)?[ \t]*\n(.*?)```", re.S)
EXAMPLE_VERDICT = re.compile(r"EXAMPLE\s+(\d+)\s*:\s*(KEEP|DROP)", re.I)


def protected_lines(prompt: str, entry_point: str) -> list[str]:
    """Lines a cleanup must keep: signatures, doctest lines and their outputs, example calls."""
    lines = [line.strip() for line in prompt.splitlines()]
    keep = []
    for index, line in enumerate(lines):
        doctest_output = index > 0 and lines[index - 1].startswith(">>>") and line
        if (
            line.startswith((">>>", "def ", "async def "))
            or doctest_output
            or re.search(r"(?<![\w.])" + re.escape(entry_point) + r"\s*\(", line)
        ):
            keep.append(line)
    return keep


def accept_cleanup(original: str, cleaned: str | None, entry_point: str) -> str | None:
    """The cleaned task if it only deletes text (at most MAX_DELETED_SHARE of it) and keeps the
    signature, every example and the function name; else None."""
    if not cleaned or not cleaned.strip() or cleaned.strip() == original.strip():
        return None
    deleted = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, original, cleaned, autojunk=False
    ).get_opcodes():
        if tag == "delete":
            deleted += i2 - i1
        elif tag != "equal" and (original[i1:i2].strip() or cleaned[j1:j2].strip()):
            return None  # a replacement or an insertion that is not only whitespace
    if deleted > MAX_DELETED_SHARE * len(original):
        return None
    remaining = [line.strip() for line in cleaned.splitlines()]
    position = 0
    for line in protected_lines(original, entry_point):
        while position < len(remaining) and remaining[position] != line:
            position += 1
        if position == len(remaining):
            return None
        position += 1
    if extract_examples(cleaned, entry_point) != extract_examples(original, entry_point):
        return None
    return cleaned


def preclean(env: ClarificationEnvironment, prompt: str, entry_point: str) -> str:
    """The task with one contradictory sentence deleted, or the task unchanged."""
    try:
        reply = env.llm(_fill(PRECLEAN_TEMPLATE, prompt=prompt, entry_point=entry_point)) or ""
    except Exception:
        return prompt
    if reply.strip().upper().startswith("UNCHANGED"):
        return prompt
    match = TEXT_BLOCK.search(reply)
    cleaned = match.group(1).strip("\n") if match else None
    return accept_cleanup(prompt, cleaned, entry_point) or prompt


def parse_checks(
    reply: str, entry_point: str, examples: list[tuple[str, tuple, Any]]
) -> list[tuple[str, tuple, Any]]:
    """The stated examples not dropped, then the calls the answer settles."""
    dropped = {
        int(number) - 1
        for number, verdict in EXAMPLE_VERDICT.findall(reply or "")
        if verdict.upper() == "DROP"
    }
    checks = [example for index, example in enumerate(examples) if index not in dropped]
    for call, args, (has_expected, expected) in parse_probe_calls(reply or "", entry_point):
        if has_expected and all(not (a == args and same_value(e, expected)) for _, a, e in checks):
            checks.append((call, args, expected))
    return checks[:MAX_CHECKS]


def sandbox_value(kind: str, info: str) -> tuple[bool, Any]:
    if kind == "NONE":
        return True, None
    if kind != "VALUE":
        return False, None
    try:
        return True, ast.literal_eval(info)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return False, None


def check_passes(
    env: ClarificationEnvironment,
    codes: list[str],
    entry_point: str,
    checks: list[tuple[str, tuple, Any]],
) -> list[list[bool] | None]:
    """Per implementation, which checks it passes (None when it could not be run)."""
    reports = run_candidates(env, codes, entry_point, [args for _, args, _ in checks])
    if reports is None:
        return [None] * len(codes)
    passes: list[list[bool] | None] = []
    for report in reports:
        if report is None or report["load_error"]:
            passes.append(None)
            continue
        row = []
        for (kind, info), (_, _, expected) in zip(report["results"], checks, strict=True):
            found, value = sandbox_value(kind, info)
            row.append(found and same_value(value, expected))
        passes.append(row)
    return passes


class LAASeR_PinpointChecks(LAASeR_PinpointSMT):
    DEFAULT_CONFIG = {
        **LAASeR_PinpointSMT.DEFAULT_CONFIG,
        "reorder_arguments": True,
        "format_question": "dedicated",
        "preclean": True,
        "example_checks": True,
        "answer_checks": True,
        # Implementations written with the answer next to v7's, compared on the checks.
        "finals": 2,
        "check_repairs": 2,
    }

    def run(self, env: ClarificationEnvironment, problem: dict[str, Any]) -> str:
        entry_point = problem["entry_point"]
        if self.config["preclean"]:
            problem = {**problem, "prompt": preclean(env, problem["prompt"], entry_point)}
        prompt = problem["prompt"]
        rules = _rules(entry_point)
        if self.config["format_question"] in ("contrast", "dedicated") and self.format_question(
            prompt
        ):
            rules = f"{rules.rstrip()}\n{ANSWER_OVERRIDES_RULE}"
        candidate, clarification, answered, coding_problem = "", "", False, problem
        try:
            candidate, clarification, answered, coding_problem = self.solve(env, problem, rules)
        except (TooManyQuestionException, LimitsExceededException):
            pass
        except Exception:
            pass
        if _is_placeholder(candidate, entry_point):
            try:
                response = env.llm(_fill(FALLBACK_TEMPLATE, prompt=prompt, rules=rules))
                fallback = _finalize(env, problem, response, "")
                if fallback and not _is_placeholder(fallback, entry_point):
                    candidate = fallback
            except Exception:
                pass
        if self.config["verify"] and not _is_placeholder(candidate, entry_point):
            candidate = verify_by_execution(
                env,
                coding_problem,
                candidate,
                clarification,
                answered,
                rules,
                int(self.config["candidates"]),
            )
        if not _is_placeholder(candidate, entry_point):
            try:
                candidate = self.check_and_select(
                    env, coding_problem, candidate, clarification, answered, rules
                )
            except Exception:
                pass
        if (
            self.config["reorder_arguments"]
            and candidate
            and not shows_signature(problem)
            and not ORDER_IN_ANSWER.search(clarification or "")
        ):
            candidate = collection_first(candidate, entry_point)
        if self.config["call_adapter"] and candidate:
            candidate = call_adapter(candidate, entry_point)
        return candidate

    def checks(
        self,
        env: ClarificationEnvironment,
        prompt: str,
        entry_point: str,
        clarification: str,
        answered: bool,
    ) -> list[tuple[str, tuple, Any]]:
        examples = []
        if self.config["example_checks"]:
            examples = [
                (example["call"], example["args"], example["expected"])
                for example in extract_examples(prompt, entry_point)
            ]
        if not (answered and self.config["answer_checks"]):
            return examples[:MAX_CHECKS]
        numbered = "\n".join(
            f"{number}. {call} == {expected!r}"
            for number, (call, _, expected) in enumerate(examples, 1)
        )
        reply = env.llm(
            _fill(
                CHECKS_TEMPLATE,
                prompt=prompt,
                entry_point=entry_point,
                clarification=clarification,
                examples=numbered or "(none)",
            )
        )
        return parse_checks(reply, entry_point, examples)

    def check_and_select(
        self,
        env: ClarificationEnvironment,
        problem: dict[str, Any],
        candidate: str,
        clarification: str,
        answered: bool,
        rules: str,
    ) -> str:
        """The implementation that passes most checks, repaired against the ones it fails."""
        prompt, entry_point = problem["prompt"], problem["entry_point"]
        checks = self.checks(env, prompt, entry_point, clarification, answered)
        if not checks:
            return candidate
        codes = [candidate]
        for _ in range(int(self.config["finals"])):
            response = env.llm(
                _fill(CODE_TEMPLATE, prompt=prompt, clarification=clarification, rules=rules)
            )
            code = _check_code(response, entry_point)[0]
            if code and not _is_placeholder(code, entry_point):
                codes.append(code)
        passes = check_passes(env, codes, entry_point, checks)
        rows = [row for row in passes if row is not None]
        if not rows:
            return candidate
        # A check no implementation passes is one the answer overrides or a corrupted example.
        kept = [index for index in range(len(checks)) if any(row[index] for row in rows)]
        if not kept:
            return candidate
        checks = [checks[index] for index in kept]
        scores = [-1 if row is None else sum(row[index] for index in kept) for row in passes]
        best = max(range(len(codes)), key=lambda number: (scores[number], -number))
        code = codes[best]
        for _ in range(int(self.config["check_repairs"])):
            row = check_passes(env, [code], entry_point, checks)[0]
            if row is None or all(row):
                break
            failures = "\n".join(
                f"- {call} should return {expected!r}"
                for (call, _, expected), ok in zip(checks, row, strict=True)
                if not ok
            )
            response = env.llm(
                _fill(
                    REPAIR_TEMPLATE,
                    prompt=prompt,
                    clarification=clarification,
                    code=code,
                    failures=failures,
                    rules=rules,
                )
            )
            repaired = _check_code(response, entry_point)[0]
            if not repaired:
                break
            repaired_row = check_passes(env, [repaired], entry_point, checks)[0]
            if repaired_row is None or sum(repaired_row) <= sum(row):
                break
            code = repaired
        return code
