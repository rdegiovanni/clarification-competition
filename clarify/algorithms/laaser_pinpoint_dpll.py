# SPDX-FileCopyrightText: 2026 Submitter <submitter@email.com>
#
# SPDX-License-Identifier: Open Source License like MIT, Apache 2.0, ...

"""Algorithm name.

LAASeR PinpointDPLL algorithm.

`LAASeR_Pinpoint` (the measured best: 0.698 mean TDS over 3 full val runs) is kept verbatim: its
audit decides whether to ask and writes the question, and its coding/repair path is unchanged.
A propositional layer is added beside it, with one narrow power -- it can only change the
question when it holds a certificate that the task contradicts itself:

1. FORMALIZE (one extra LLM call). Points the text leaves open become boolean atoms with two
   plain-English readings; every statement, example or type hint that forces a reading becomes
   an EVIDENCE clause tagged with its exact quote. Quotes are verified against the task text
   mechanically, so an invented quote never enters the theory. Optional per-reading Python checks
   are executed on the prompt's own examples in one `exec_code` call (HumanEval-style prompts;
   MBPP prompts carry no examples), and an example that satisfies one reading's check while
   violating the other's becomes one more evidence clause.
2. DECIDE (in-process DPLL with unit propagation and pure-literal elimination). Satisfiable:
   nothing changes, the run is exactly Pinpoint. Unsatisfiable: a deletion-based minimal
   unsatisfiable core over the evidence groups names two distinct statements that force opposite
   readings of one atom. If the audit decided to code anyway, the question becomes: 'The task
   says "X" but also "Y". Which is intended: A, or B?'. Replacing a question the audit already
   asked is opt-in (`replace_question`): measured on smoke-70, the audit's own questions are more
   concrete and draw more informative answers than this template.

The layer never suppresses a question, never adds "facts" to the coding prompt, and any failure
inside it (parse, sandbox, budget) falls back to plain Pinpoint behaviour. One change to the
shared Pinpoint path: a final function whose body does nothing (`pass`, a bare `return`, only a
`raise`) now counts as unusable and goes through the bounded repair step.

Team: LAASeR - LIST
Team Members: Matias Brizzio, Jordi Cabot, Renzo Degiovanni
Main Contact: main.contact@email.com
"""

from __future__ import annotations

import ast
import base64
import re
from collections import Counter
from typing import Any

from clarify.baselines import ClarificationAlgorithmBase
from clarify.env import ClarificationEnvironment, LimitsExceededException, TooManyQuestionException
from clarify.runtime import _validate_and_parse_evalplus_result

MAX_REPAIR_ATTEMPTS = 2
MIN_QUESTION_LENGTH = 10
MAX_QUESTION_LENGTH = 600

CODING_RULES = """
Rules for the implementation:
1. Name the function exactly `{entry_point}`, even if the task text uses another name. Keep the
   parameters shown in the task; if none are shown, use the most natural parameters for the
   description.
2. The hidden tests only compare return values. Never weaken or complicate the logic to satisfy
   requirements they cannot observe (time complexity, "no loops", "no recursion", style).
3. Where the task is still ambiguous or contradictory, choose the most standard, least surprising
   behaviour for a function with this name and purpose.
4. Write only the function (plus any imports and helpers it needs) in a single ```python block:
   no prints, no input(), no example usage.
""".strip()

AUDIT_TEMPLATE = """
You are about to implement a Python function for a user. The task text below may have been
edited so that it is vague, incomplete or self-contradictory. Hidden tests will call
`{entry_point}` and compare its return values with the behaviour the user really intends.
Before coding you may ask the user ONE clarifying question. A question is cheap, but
implementing the wrong behaviour fails the tests.

Task:
<<<
{prompt}
>>>

STEP 1 - DEFECTS. List every place where the task does not uniquely determine the values that
`{entry_point}` must return. Check in particular for:
- CONTRADICTION: two statements, or a statement and an example / signature / type hint, that
  cannot both hold.
- VAGUE: a word or phrase whose interpretation changes the output (e.g. "similar", "certain",
  "okay", "large", "standard").
- MISSING: something the code needs that the text never fixes: the arguments and their
  structure, the return type or format, a formula, a threshold, a tie-break rule, the result
  for a special input.
- ODD: an unusual extra requirement that looks out of place for this function.
Write one line per defect:
- <TYPE> | "<exact phrase from the task, or: not stated>" | reading A: ... | reading B: ... | IMPACT: HIGH or LOW
IMPACT is HIGH when the two readings return different values on ordinary inputs, and LOW when
they differ only on rare edge inputs. Requirements that tests cannot observe (time complexity,
"no loops", "no recursion", style, comments) are never defects. If there are none, write: - none

STEP 2 - DECISION.
If no defect is HIGH and the task (with its examples) fixes both the arguments and the exact
return format, write the line `DECISION: CODE` followed by the complete implementation.
Otherwise write the line `DECISION: ASK` followed by exactly one line:
QUESTION: <your question>
Ask about the HIGH defect that would make the most tests fail (contradictions and the return
format first, then missing rules and vague terms, edge cases last). Quote or name the phrase
and offer the competing readings, so that the complete answer is exactly one fact. Example:
QUESTION: The task says "a frequency similar to the value" - should the frequency be exactly equal to the value, or at least the value?
Ask about one thing only, and never ask for test cases or for the implementation.

{rules}
""".strip()

CODE_TEMPLATE = """
Implement the following Python task.

Task:
<<<
{prompt}
>>>
{clarification}
{rules}
""".strip()

CLARIFICATION_BLOCK = """
You asked the user a clarifying question. Their answer is authoritative: where it conflicts with
the task text, follow the answer.
Question: {question}
Answer: {answer}
"""

REPAIR_TEMPLATE = """
Your previous answer to the task below cannot be used: {problem}

Task:
<<<
{prompt}
>>>
{clarification}
Previous answer:
<<<
{response}
>>>

Return the corrected, complete implementation of `{entry_point}` in a single ```python block.
""".strip()

DECISION_PATTERN = re.compile(r"DECISION[\s:*`]*(ASK|CODE)", re.IGNORECASE)
QUESTION_PATTERN = re.compile(r"QUESTION\s*:\s*(.+)", re.IGNORECASE)
PLACEHOLDER_PATTERN = re.compile(r"\{(\w+)\}")


def _fill(template: str, **fields: str) -> str:
    # One pass over the template's own placeholders: the inserted values (task text, model or
    # user output) routinely contain literal braces and must never be substituted into.
    return PLACEHOLDER_PATTERN.sub(lambda m: fields.get(m.group(1), m.group(0)), template)


def _rules(entry_point: str) -> str:
    return _fill(CODING_RULES, entry_point=entry_point)


def _clarification_block(question: str | None, answer: str | None) -> str:
    if not question or not answer:
        return ""
    return _fill(CLARIFICATION_BLOCK, question=question, answer=answer)


def _parse_decision(response: str) -> str | None:
    match = DECISION_PATTERN.search(response)
    return match.group(1).upper() if match else None


def _parse_question(response: str) -> str | None:
    match = QUESTION_PATTERN.search(response)
    if not match:
        return None
    question = match.group(1).split("```", 1)[0].strip().strip("*`'\" ").strip()
    if len(question) < MIN_QUESTION_LENGTH:
        return None
    return question[:MAX_QUESTION_LENGTH]


def _check_code(response: str, entry_point: str) -> tuple[str | None, str | None]:
    """Returns (code, problem); problem is None when the code is usable as-is."""
    try:
        code = _validate_and_parse_evalplus_result(response)
    except ValueError:
        return None, "it does not contain a ```python code block."

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return code, f"the code is not valid Python ({e.msg}, line {e.lineno})."

    # Only module-level names count: the tests call the entry point at module scope.
    defined = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    defined |= {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    if entry_point not in defined:
        return code, f"it does not define a function named exactly `{entry_point}`."

    # Not in Pinpoint: a body that does nothing parses fine but can never pass a test.
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == entry_point
        ),
        None,
    )
    if function is not None and _is_stub(function):
        return code, (
            f"the body of `{entry_point}` does nothing (it only passes, raises or returns "
            "nothing); write the complete implementation."
        )

    return code, None


def _is_stub(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when the body only passes, raises, returns nothing, or holds bare constants."""
    for stmt in function.body:
        if isinstance(stmt, (ast.Pass, ast.Raise)):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue  # docstring or `...`
        if isinstance(stmt, ast.Return) and (
            stmt.value is None
            or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)
        ):
            continue
        return False
    return True


def _alias_entry_point(code: str, entry_point: str) -> str | None:
    """Last resort when repairs fail: alias the only top-level function to the entry point."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    top_level = [
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if len(top_level) != 1:
        return None
    return f"{code.rstrip()}\n\n{entry_point} = {top_level[0]}\n"


def _finalize(
    env: ClarificationEnvironment,
    problem: dict[str, Any],
    response: str,
    clarification: str,
) -> str:
    """Validates the response, repairing it a bounded number of times; returns best code."""
    entry_point = problem["entry_point"]
    best = ""
    for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
        code, issue = _check_code(response, entry_point)
        if code is not None and issue is None:
            return code
        if code is not None and not best:
            best = code
        if attempt == MAX_REPAIR_ATTEMPTS:
            break
        response = env.llm(
            _fill(
                REPAIR_TEMPLATE,
                problem=issue,
                prompt=problem["prompt"],
                clarification=clarification,
                response=response,
                entry_point=entry_point,
            )
        )

    return _alias_entry_point(best, entry_point) or best


# =================================================================================================
# Propositional layer: everything below only ever produces an optional contradiction certificate.
# =================================================================================================

MAX_ATOMS = 12
MAX_EXAMPLES = 8
MAX_CHECK_RUNS = 64  # predicate evaluations per grounding script
MAX_QUOTE_LENGTH = 160

FORMALIZE_TEMPLATE = """
Below is the task text for a Python function `{entry_point}`. It may have been edited so that
some of its statements contradict each other or its examples. Formalize it as a small
propositional theory, using exactly the line formats below, one item per line, nothing else.

Task:
<<<
{prompt}
>>>

ATOM - one line for each point where two readings of the task make `{entry_point}` return
different values:
ATOM <name> | A: <reading A, one short plain-English clause> | B: <reading B, one short plain-English clause>

CHECK - when you can, one Python boolean expression per reading, using only the parameter names
and `result` (the return value), true exactly when `result` is consistent with that reading:
CHECK <name> | A: <python expression> | B: <python expression>

EVIDENCE - for each statement, example or type hint that, read literally, forces a reading,
quote it exactly:
EVIDENCE "<exact quote from the task>" => <name>=<A or B>
When two parts of the task conflict, write an EVIDENCE line for EACH of them and do not decide
which one is right. A vague phrase forces nothing: give it no EVIDENCE line.

If nothing in the task is open, write the single line: ATOM none
""".strip()

# Runs inside the sandbox. The payload is base64(repr((params, examples, checks))) so no model
# text is ever spliced into the script source.
GROUNDING_SCRIPT = """
import ast
import base64
import collections
import copy
import itertools
import math
import re
import signal


def on_alarm(signum, frame):
    raise TimeoutError()


signal.signal(signal.SIGALRM, on_alarm)
params, examples, checks = ast.literal_eval(base64.b64decode("{payload}").decode())
namespace = {"math": math, "re": re, "collections": collections, "itertools": itertools}
for ci, expr in enumerate(checks):
    try:
        fn = eval("lambda " + ", ".join(list(params) + ["result"]) + ": (" + expr + ")", namespace)
    except BaseException:
        fn = None
    for ei, (args, expected) in enumerate(examples):
        out = "E"
        if fn is not None:
            try:
                signal.alarm(1)
                out = "T" if fn(*copy.deepcopy(args), copy.deepcopy(expected)) else "F"
            except BaseException:
                out = "E"
            finally:
                signal.alarm(0)
        print("CHK", ci, ei, out)
""".strip()

ATOM_LINE = re.compile(r"^ATOM\b\s*:?\s*(.*)$", re.IGNORECASE)
READINGS = re.compile(
    r"\|\s*(?:reading\s+)?A\s*[:)]\s*(.*?)\s*\|\s*(?:reading\s+)?B\s*[:)]\s*(.*?)\s*$", re.I
)
CHECK_LINE = re.compile(
    r"^CHECK\b\s*:?\s*([A-Za-z_][\w-]*)\s*\|\s*A\s*:\s*(.*?)\s*\|\s*B\s*:\s*(.*?)\s*$",
    re.IGNORECASE,
)
EVIDENCE_LINE = re.compile(r"^EVIDENCE\b\s*:?\s*(.+?)\s*=>\s*(.+?)\s*$", re.IGNORECASE)
LITERAL = re.compile(r"([A-Za-z_][\w-]*)\s*(?:==|=|:)\s*['\"]?(A|B|TRUE|FALSE)\b", re.I)
CHECK_RESULT = re.compile(r"^CHK (\d+) (\d+) ([TFE])$", re.MULTILINE)
INLINE_EXAMPLE_OP = re.compile(r"\s*(?:==>|==|➞|=>|->|→|should return|returns|return)\s*", re.I)
LINE_PREFIX = re.compile(r"^[\s\-*•>#\d.)]+")
COMMON_WORDS = frozenset(
    "the that this with from function return returns should which given each into only when "
    "then than have will what there their value values list number numbers string strings "
    "element elements write task says also".split()
)


# --- DPLL core. Literals are non-zero ints: v = atom v holds reading A, -v = reading B. --------


def _assign(clauses: list[frozenset[int]], lit: int) -> list[frozenset[int]] | None:
    """Simplifies the clause set under `lit`; None if that produces an empty clause."""
    reduced = []
    for clause in clauses:
        if lit in clause:
            continue
        if -lit in clause:
            clause = clause - {-lit}
            if not clause:
                return None
        reduced.append(clause)
    return reduced


def _dpll(clauses: list[frozenset[int]], assignment: dict[int, bool]) -> dict[int, bool] | None:
    assignment = dict(assignment)
    while True:
        unit = next((c for c in clauses if len(c) == 1), None)
        if unit is not None:  # unit propagation
            (lit,) = unit
            assignment[abs(lit)] = lit > 0
            clauses = _assign(clauses, lit)
            if clauses is None:
                return None
            continue
        literals = {lit for clause in clauses for lit in clause}
        pure = {lit for lit in literals if -lit not in literals}
        if not pure:  # pure-literal elimination
            break
        for lit in pure:
            assignment[abs(lit)] = lit > 0
        clauses = [c for c in clauses if not (c & pure)]

    if not clauses:
        return assignment
    counts = Counter(abs(lit) for clause in clauses for lit in clause)
    var = max(counts, key=lambda v: (counts[v], -v))
    for lit in (var, -var):
        reduced = _assign(clauses, lit)
        if reduced is None:
            continue
        result = _dpll(reduced, {**assignment, var: lit > 0})
        if result is not None:
            return result
    return None


def dpll_solve(clauses: list[list[int]], num_vars: int) -> dict[int, bool] | None:
    """A total satisfying assignment {var: bool}, or None if the clauses are unsatisfiable."""
    clause_sets = []
    for clause in clauses:
        clause_set = frozenset(clause)
        if not clause_set:
            return None
        if not any(-lit in clause_set for lit in clause_set):  # drop tautologies
            clause_sets.append(clause_set)
    model = _dpll(clause_sets, {})
    if model is None:
        return None
    for var in range(1, num_vars + 1):
        model.setdefault(var, True)
    return model


def minimal_unsat_core(groups: list[list[list[int]]], num_vars: int) -> list[int] | None:
    """Indices of a minimal unsatisfiable subset of clause groups (deletion-based), or None if
    all groups together are satisfiable. Minimal: dropping any one group makes it satisfiable."""

    def unsat(indices: list[int]) -> bool:
        return dpll_solve([c for i in indices for c in groups[i]], num_vars) is None

    core = list(range(len(groups)))
    if not unsat(core):
        return None
    i = 0
    while i < len(core):
        trial = core[:i] + core[i + 1 :]
        if unsat(trial):
            core = trial
        else:
            i += 1
    return core


# --- Mechanical reading of the prompt (no LLM). ---------------------------------------------------


def _balanced_parens(text: str, start: int) -> int | None:
    """Index just past the bracket group opening at text[start], skipping string literals."""
    depth = 0
    quote = None
    i = start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def find_stub_params(prompt: str, entry_point: str) -> list[str] | None:
    """Positional parameter names of `def entry_point(...)` in the prompt, or None if absent."""
    match = re.search(r"def\s+" + re.escape(entry_point) + r"\s*\(", prompt)
    if not match:
        return None
    end = _balanced_parens(prompt, match.end() - 1)
    if end is None:
        return None
    try:
        tree = ast.parse(f"def f{prompt[match.end() - 1 : end]}: pass")
    except SyntaxError:
        return None
    args = tree.body[0].args
    return [a.arg for a in (*args.posonlyargs, *args.args)]


def _literal(text: str) -> tuple[bool, Any]:
    """Parses a Python literal; falls back to the longest word-prefix that parses, so trailing
    prose ("3 (since ...)") does not lose an example."""
    words = text.strip().split()
    for k in range(len(words), max(len(words) - 12, 0), -1):
        candidate = " ".join(words[:k]).rstrip(".,;:").strip()
        if not candidate:
            continue
        try:
            value = ast.literal_eval(candidate)
            ast.literal_eval(repr(value))  # must survive the trip into the sandbox
            return True, value
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            continue
    return False, None


def extract_examples(prompt: str, entry_point: str) -> list[dict[str, Any]]:
    """Examples `entry_point(args) -> value` written in the prompt (doctest or inline style)."""
    examples: list[dict[str, Any]] = []
    seen: set[str] = set()
    lines = prompt.splitlines()
    call = re.compile(r"(?<![\w.])" + re.escape(entry_point) + r"\s*\(")
    for idx, line in enumerate(lines):
        for match in call.finditer(line):
            end = _balanced_parens(line, match.end() - 1)
            if end is None:
                continue
            inner = line[match.end() : end - 1]
            ok, args = _literal("(" + inner + ",)") if inner.strip() else (True, ())
            if not ok or not isinstance(args, tuple):
                continue
            rest = line[end:]
            op = INLINE_EXAMPLE_OP.match(rest)
            if op:
                ok, expected = _literal(rest[op.end() :])
            elif line.strip().startswith(">>>") and not rest.strip():
                following = [
                    nxt.strip()
                    for nxt in lines[idx + 1 : idx + 4]
                    if nxt.strip() and not nxt.strip().startswith(">>>")
                ]
                ok, expected = _literal(following[0]) if following else (False, None)
            else:
                ok = False
            if not ok:
                continue
            key = repr((args, expected))
            if key in seen:
                continue
            seen.add(key)
            shown = f"{entry_point}{line[match.end() - 1 : end]} == {expected!r}"
            examples.append({"args": args, "expected": expected, "quote": shown})
            if len(examples) >= MAX_EXAMPLES:
                return examples
    return examples


# --- Formalization parsing. -----------------------------------------------------------------------


def _norm_name(raw: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", raw.strip().strip("`'\"").lower()).strip("_")


def _clean_reading(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip().strip("`'\"").strip().rstrip(" .;?!")
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        text = text[0].lower() + text[1:]
    return text


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def quote_in_text(quote: str, text: str) -> bool:
    """True if the quote's word tokens occur contiguously in the text (case/punctuation-blind)."""
    needle, hay = _tokens(quote), _tokens(text)
    if not needle:
        return False
    n = len(needle)
    return any(hay[i : i + n] == needle for i in range(len(hay) - n + 1))


def parse_formalization(response: str, prompt: str, entry_point: str) -> dict[str, Any] | None:
    """Returns {atoms, evidence}, or None when the response contains no usable ATOM line."""
    lines = [
        LINE_PREFIX.sub("", raw.replace("**", "").replace("`", "")) for raw in response.splitlines()
    ]
    atoms: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    for line in lines:
        match = ATOM_LINE.match(line)
        readings = READINGS.search(match.group(1)) if match else None
        if not readings:
            continue
        head = match.group(1)[: readings.start()].split("|")[0].split()
        name = _norm_name(head[0]) if head else ""
        reading_a, reading_b = _clean_reading(readings.group(1)), _clean_reading(readings.group(2))
        if (
            not name
            or name in by_name
            or len(atoms) >= MAX_ATOMS
            or not reading_a
            or not reading_b
            or reading_a == reading_b
        ):
            continue
        atom = {"name": name, "A": reading_a, "B": reading_b, "check_A": "", "check_B": ""}
        atoms.append(atom)
        by_name[name] = atom
    if not atoms:
        return None

    for line in lines:
        match = CHECK_LINE.match(line)
        atom = by_name.get(_norm_name(match.group(1))) if match else None
        if atom is None:
            continue
        for side, expr in (("A", match.group(2)), ("B", match.group(3))):
            expr = expr.strip()
            if not expr or expr.lower() in ("none", "n/a", "-"):
                continue
            try:
                ast.parse(expr, mode="eval")
            except SyntaxError:
                continue
            atom["check_" + side] = expr

    evidence: list[dict[str, Any]] = []
    for line in lines:
        match = EVIDENCE_LINE.match(line)
        if not match:
            continue
        quote = match.group(1).strip().strip("“”\"'").strip()
        literals = LITERAL.findall(match.group(2))
        if not quote or not literals:
            continue
        if not (quote_in_text(quote, prompt) or _norm_name(quote) == _norm_name(entry_point)):
            continue  # an unverifiable quote never enters the theory
        clause = [
            (_norm_name(name), "A" if side.upper() in ("A", "TRUE") else "B")
            for name, side in literals
        ]
        if any(name not in by_name for name, _ in clause):
            continue  # dropping one literal would strengthen the clause: drop it all
        evidence.append({"quote": quote[:MAX_QUOTE_LENGTH], "clause": clause, "source": "text"})
    return {"atoms": atoms, "evidence": evidence}


# --- Grounding: run the checks on the prompt's own examples in the sandbox. -----------------------


def ground_examples(
    env: ClarificationEnvironment,
    atoms: list[dict[str, Any]],
    examples: list[dict[str, Any]],
    params: list[str] | None,
) -> list[dict[str, Any]]:
    """Evidence clauses derived by execution; [] whenever grounding is impossible or fails."""
    if not examples or params is None:
        return []
    checks: list[str] = []
    slots: list[tuple[int, str]] = []
    for i, atom in enumerate(atoms):
        for side in ("A", "B"):
            if atom["check_" + side]:
                slots.append((i, side))
                checks.append(atom["check_" + side])
    if not checks:
        return []
    examples = examples[: max(1, MAX_CHECK_RUNS // len(checks))]
    payload = repr((list(params), [(ex["args"], ex["expected"]) for ex in examples], checks))
    try:
        ast.literal_eval(payload)  # the sandbox must be able to read it back
        output = env.exec_code(
            _fill(GROUNDING_SCRIPT, payload=base64.b64encode(payload.encode()).decode())
        )
    except Exception:
        return []

    results = {(int(ci), int(ei)): out for ci, ei, out in CHECK_RESULT.findall(output or "")}
    evidence = []
    for ei, example in enumerate(examples):
        verdict: dict[int, dict[str, str]] = {}
        for ci, (atom_i, side) in enumerate(slots):
            verdict.setdefault(atom_i, {})[side] = results.get((ci, ei), "E")
        for atom_i, sides in verdict.items():
            # Only asymmetric verdicts count (one reading's check holds, the other's fails), so a
            # single buggy check can never decide anything on its own.
            if sides.get("A") == "T" and sides.get("B") == "F":
                side = "A"
            elif sides.get("A") == "F" and sides.get("B") == "T":
                side = "B"
            else:
                continue
            evidence.append(
                {
                    "quote": example["quote"],
                    "clause": [(atoms[atom_i]["name"], side)],
                    "source": "example",
                }
            )
    return evidence


# --- Certificate, question, and the "does the audit already ask about it" test. -------------------


def _overlapping(first: str, second: str) -> bool:
    return quote_in_text(first, second) or quote_in_text(second, first)


def certify_contradiction(
    formal: dict[str, Any], extra_evidence: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """{atom, quotes: (supports A, supports B)} when the evidence is unsatisfiable and its minimal
    core contains two distinct, non-overlapping statements forcing opposite readings of one atom;
    otherwise None."""
    atoms = formal["atoms"]
    index = {atom["name"]: i + 1 for i, atom in enumerate(atoms)}
    group_of: dict[tuple[str, str], int] = {}
    groups: list[list[list[int]]] = []
    labels: list[str] = []
    for ev in [*formal["evidence"], *extra_evidence]:  # text first: the core keeps the earliest
        key = (ev["source"], ev["quote"])
        if key not in group_of:
            group_of[key] = len(groups)
            groups.append([])
            labels.append(ev["quote"])
        groups[group_of[key]].append(
            [index[name] if side == "A" else -index[name] for name, side in ev["clause"]]
        )

    core = minimal_unsat_core(groups, len(atoms))
    if core is None:
        return None
    hits = Counter(abs(lit) for i in core for clause in groups[i] for lit in clause)
    for var, _ in hits.most_common():
        pro = [labels[i] for i in core if any(var in clause for clause in groups[i])]
        con = [labels[i] for i in core if any(-var in clause for clause in groups[i])]
        for first in pro:
            for second in con:
                if not _overlapping(first, second):
                    return {"atom": atoms[var - 1], "quotes": (first, second)}
    return None


def _short(quote: str) -> str:
    quote = re.sub(r"\s+", " ", quote).strip()
    return quote if len(quote) <= MAX_QUOTE_LENGTH else quote[: MAX_QUOTE_LENGTH - 3] + "..."


def build_core_question(certificate: dict[str, Any]) -> str:
    first, second = (_short(q) for q in certificate["quotes"])
    atom = certificate["atom"]
    question = (
        f'The task says "{first}" but also "{second}". '
        f"Which is intended: {atom['A']}, or {atom['B']}?"
    )
    return question[:MAX_QUESTION_LENGTH]


LITERAL_SPAN = re.compile(r"\[[^\]]*\]|\([^()]*\)|'[^']*'|\"[^\"]*\"|\d+(?:\.\d+)?")


def _stems(text: str) -> set[str]:
    # A crude 5-letter stem: "subtract" and "subtraction" must count as the same word.
    return {w[:5] for w in _tokens(text) if len(w) >= 4 and w not in COMMON_WORDS}


def question_mentions(question: str, quotes: tuple[str, ...]) -> bool:
    """True if the question already refers to one of the quoted statements: it contains it,
    shares at least half of its distinctive word stems, or repeats one of its literals
    (a list, tuple, string or number such as "[9,9]")."""
    asked = _stems(question)
    compact_question = re.sub(r"\s+", "", question.lower())
    for quote in quotes:
        if quote_in_text(quote, question):
            return True
        content = _stems(quote)
        if content and len(content & asked) / len(content) >= 0.5:
            return True
        literals = (re.sub(r"\s+", "", m.group(0).lower()) for m in LITERAL_SPAN.finditer(quote))
        if any(len(lit) >= 3 and lit in compact_question for lit in literals):
            return True
    return False


def atomic_question(question: str | None) -> str | None:
    """Keeps only the first question of a bundle ("...? Also, ...?")."""
    if not question:
        return None
    question = re.split(r"\s+(?:Also|Additionally|And also|Furthermore)\b[,:]?\s", question)[0]
    if "?" in question:
        question = question[: question.index("?") + 1]
    return question if len(question) >= MIN_QUESTION_LENGTH else None


def find_certificate(
    env: ClarificationEnvironment, problem: dict[str, Any]
) -> dict[str, Any] | None:
    """The whole propositional layer. Never raises: any failure means "no certificate"."""
    prompt, entry_point = problem["prompt"], problem["entry_point"]
    try:
        response = env.llm(_fill(FORMALIZE_TEMPLATE, prompt=prompt, entry_point=entry_point))
        formal = parse_formalization(response, prompt, entry_point)
        if formal is None:
            return None
        params = find_stub_params(prompt, entry_point)
        examples = extract_examples(prompt, entry_point)
        extra = ground_examples(env, formal["atoms"], examples, params)
        return certify_contradiction(formal, extra)
    except Exception:
        return None


class LAASeR_PinpointDPLL(ClarificationAlgorithmBase):
    # replace_question is off by default: on smoke-70 r1 the four replacements lost HumanEval/72
    # and Mbpp/888, both of which the audit's own (more concrete) question handled better.
    DEFAULT_CONFIG = {"replace_question": False, "atomic_question": False}

    def run(self, env: ClarificationEnvironment, problem: dict[str, Any]) -> str:
        prompt = problem["prompt"]
        entry_point = problem["entry_point"]
        rules = _rules(entry_point)
        candidate = ""

        try:
            audit = env.llm(
                _fill(AUDIT_TEMPLATE, prompt=prompt, entry_point=entry_point, rules=rules)
            )
            decision = _parse_decision(audit)
            question = _parse_question(audit)
            if self.config["atomic_question"]:
                question = atomic_question(question) or question

            certificate = find_certificate(env, problem)
            if certificate is not None:
                core_question = build_core_question(certificate)
                if decision == "CODE" or question is None:
                    # The audit would code straight through a certified contradiction.
                    decision, question = "ASK", core_question
                elif self.config["replace_question"] and not question_mentions(
                    question, certificate["quotes"]
                ):
                    question = core_question

            if decision == "CODE" or (decision is None and question is None):
                candidate = _check_code(audit, entry_point)[0] or ""
                return _finalize(env, problem, audit, "") or candidate

            answer = None
            if question and env.can_ask():
                try:
                    answer = env.ask_human(question)
                except TooManyQuestionException:
                    answer = None

            clarification = _clarification_block(question, answer)
            response = env.llm(
                _fill(CODE_TEMPLATE, prompt=prompt, clarification=clarification, rules=rules)
            )
            candidate = _check_code(response, entry_point)[0] or candidate
            candidate = _finalize(env, problem, response, clarification) or candidate
        except (TooManyQuestionException, LimitsExceededException):
            pass
        except Exception:
            # Never lose an already-usable candidate to an unexpected failure.
            pass

        return candidate
