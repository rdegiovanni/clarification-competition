# SPDX-FileCopyrightText: 2026 Submitter <submitter@email.com>
#
# SPDX-License-Identifier: Open Source License like MIT, Apache 2.0, ...

"""Algorithm name.

LAASeR FormalDPLL algorithm.

The task text is formalized as a small propositional theory whose clauses carry provenance, and an
in-process DPLL solver decides what to ask:

1. FORMALIZE (one LLM call). Each point the text leaves open becomes a boolean atom with two
   plain-English readings (A/B), a kind (CONTRADICTION/FORMAT/RULE/VAGUE/ODD/EDGE), an impact
   rating, and optional executable checks (a Python predicate over the arguments and `result` per
   reading). Every statement, example or type hint that forces a reading becomes an EVIDENCE
   clause tagged with the exact quote it came from. Quotes are verified against the task text
   mechanically; unverifiable evidence is dropped, so a hallucinated quote can never settle an
   atom.
2. GROUND (at most one `exec_code` call). Doctest/inline examples are extracted from the prompt
   without the LLM, and each atom's checks are executed on them in the sandbox; an example that
   satisfies one reading's check and violates the other's becomes an extra evidence clause tagged
   with that example.
3. REASON (pure Python, no sandbox). DPLL with unit propagation, pure-literal elimination and
   default-phase branching decides satisfiability. UNSAT means the task contradicts itself: a
   deletion-based minimal unsatisfiable core over the evidence groups pinpoints the conflicting
   statements, and the question quotes both. SAT: the backbone (atoms forced in every model)
   becomes a list of settled facts for the coder; the question goes to the best free atom by
   (impact, kind, listing order). Readings are never asked as code, so questions stay atomic and
   free of implementation details.
4. CODE with the answer (authoritative), the backbone facts, and -- when the task shows no `def`
   line -- an optional trailing parameter so calls with an extra length/count argument still work.

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
MAX_ATOMS = 12
MAX_EXAMPLES = 8
MAX_QUOTE_LENGTH = 160
MAX_QUESTION_LENGTH = 600
MIN_QUESTION_LENGTH = 10
MAX_CORE_ROUNDS = 8
MAX_CHECK_RUNS = 64  # predicate evaluations per grounding script

KIND_RANK = {"CONTRADICTION": 0, "FORMAT": 1, "ODD": 2, "RULE": 2, "VAGUE": 3, "EDGE": 4}
SUSPECT_KINDS = ("CONTRADICTION", "ODD")  # text "forcing" these is itself the defect


# =================================================================================================
# DPLL core. Literals are non-zero ints (DIMACS style): v means atom v is True (reading A), -v
# means it is False (reading B). Clauses are lists of literals; a clause holds if any literal does.
# =================================================================================================


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


def _dpll(
    clauses: list[frozenset[int]], assignment: dict[int, bool], phase: dict[int, bool]
) -> dict[int, bool] | None:
    assignment = dict(assignment)
    while True:
        # Unit propagation to a fixpoint.
        unit = next((c for c in clauses if len(c) == 1), None)
        if unit is not None:
            (lit,) = unit
            assignment[abs(lit)] = lit > 0
            clauses = _assign(clauses, lit)
            if clauses is None:
                return None
            continue
        # Pure-literal elimination.
        literals = {lit for clause in clauses for lit in clause}
        pure = [lit for lit in literals if -lit not in literals]
        if not pure:
            break
        for lit in pure:
            assignment[abs(lit)] = lit > 0
        pure_set = set(pure)
        clauses = [c for c in clauses if not (c & pure_set)]

    if not clauses:
        return assignment

    # Branch on the most frequent variable, trying its preferred (default) phase first.
    counts = Counter(abs(lit) for clause in clauses for lit in clause)
    var = max(counts, key=lambda v: (counts[v], -v))
    first = phase.get(var, True)
    for value in (first, not first):
        reduced = _assign(clauses, var if value else -var)
        if reduced is None:
            continue
        result = _dpll(reduced, {**assignment, var: value}, phase)
        if result is not None:
            return result
    return None


def dpll_solve(
    clauses: list[list[int]], num_vars: int, phase: dict[int, bool] | None = None
) -> dict[int, bool] | None:
    """A total satisfying assignment {var: bool}, or None if the clauses are unsatisfiable."""
    phase = phase or {}
    clause_sets = []
    for clause in clauses:
        clause_set = frozenset(clause)
        if not clause_set:
            return None
        if any(-lit in clause_set for lit in clause_set):
            continue  # tautology
        clause_sets.append(clause_set)
    model = _dpll(clause_sets, {}, phase)
    if model is None:
        return None
    for var in range(1, num_vars + 1):
        model.setdefault(var, phase.get(var, True))
    return model


def backbone(
    clauses: list[list[int]], num_vars: int, phase: dict[int, bool] | None = None
) -> dict[int, bool] | None:
    """Variables with the same value in every model ({var: value}); None if unsatisfiable."""
    model = dpll_solve(clauses, num_vars, phase)
    if model is None:
        return None
    forced = {}
    for var in range(1, num_vars + 1):
        flip = -var if model[var] else var
        if dpll_solve([*clauses, [flip]], num_vars) is None:
            forced[var] = model[var]
    return forced


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


def peel_cores(
    groups: list[list[list[int]]], num_vars: int, max_rounds: int = MAX_CORE_ROUNDS
) -> tuple[list[list[int]], list[int]]:
    """Repeatedly extracts minimal cores until the rest is satisfiable.
    Returns (cores as lists of group indices, indices of the remaining consistent groups)."""
    active = list(range(len(groups)))
    cores: list[list[int]] = []
    for _ in range(max_rounds):
        core = minimal_unsat_core([groups[i] for i in active], num_vars)
        if core is None:
            return cores, active
        core_ids = [active[i] for i in core]
        cores.append(core_ids)
        active = [i for i in active if i not in core_ids]
    if dpll_solve([c for i in active for c in groups[i]], num_vars) is None:
        active = []
    return cores, active


# =================================================================================================
# Prompts
# =================================================================================================

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

HEDGE_RULE = """
5. The task shows no `def` line, so the hidden tests may pass one extra trailing argument that
   some versions of this exercise use, such as the length of a list/string argument or a count.
   Accept it as an optional last parameter (e.g. `def {entry_point}(arr, n=None):`); when it is
   given, use it as that length/count, otherwise ignore it.
""".strip()

SIGNATURE_NOTE = """
- No `def` line is given, so the parameter list is not fixed. An optional extra trailing argument
  (such as the length of a list) is handled automatically: never make an atom for it. Make a
  FORMAT atom about the arguments only when their kind or order is genuinely unclear (e.g. one
  string vs. a list of words, or which argument comes first).
"""

FORMALIZE_TEMPLATE = """
You are about to implement a Python function for a user. The task text below may have been
edited so that it is vague, incomplete or self-contradictory. Hidden tests will call
`{entry_point}` and compare its return values with the behaviour the user really intends.
Before coding you may ask the user ONE clarifying question. A question is cheap, but
implementing the wrong behaviour fails the tests.

Task:
<<<
{prompt}
>>>

STEP 1 - FORMALIZE the task as a small propositional theory, using exactly the line formats
below (one item per line, no bullets, no other commentary).

ATOMS - one line for each point where the task does not uniquely determine the values that
`{entry_point}` must return:
ATOM <name> | <KIND> | <HIGH or LOW> | default <A or B> | "<exact phrase from the task, or: not stated>" | A: <reading A> | B: <reading B>
- name: a short lowercase identifier.
- KIND: CONTRADICTION (two statements, or a statement and an example, signature or type hint,
  cannot both hold), FORMAT (the arguments, or the return type/format), RULE (a missing formula,
  threshold, tie-break or result for a special input), VAGUE (a word or phrase whose
  interpretation changes the output), ODD (an unusual extra requirement that looks out of place
  for this function), EDGE (matters only for rare edge inputs).
- HIGH when the two readings return different values on ordinary inputs, LOW otherwise.
- A and B: two mutually exclusive readings, each one short plain-English clause about the
  behaviour (no code, no question). default: the reading you would implement without asking.
- Requirements that tests cannot observe (time complexity, "no loops", "no recursion", style)
  are never atoms. If there are no atoms at all, write the single line: ATOM none
{signature_note}
CHECKS - for each atom where you can, one Python boolean expression per reading, using only the
parameter names and `result` (the return value), true exactly when `result` is consistent with
that reading for those arguments:
CHECK <name> | A: <python expression> | B: <python expression>

EVIDENCE - for each statement, example or type hint in the task that, read literally, forces a
reading, one line quoting it exactly:
EVIDENCE "<exact quote from the task>" => <name>=<A or B>
Join alternatives with `or` (e.g. `x=A or y=B`) only when the text itself states such a link.
When two statements conflict, write an EVIDENCE line for EACH of them and do not resolve the
conflict yourself: consistency is checked mechanically. A vague phrase forces nothing, so it gets
no EVIDENCE line.

STEP 2 - DECISION. Always write this last. Either the line `DECISION: CODE` followed by the
complete implementation, or the line `DECISION: ASK` followed by exactly one line:
QUESTION: <one atomic question about the single most important atom>

{rules}
""".strip()

CODE_TEMPLATE = """
Implement the following Python task.

Task:
<<<
{prompt}
>>>
{clarification}{facts}
{rules}
""".strip()

CLARIFICATION_BLOCK = """
You asked the user a clarifying question. Their answer is authoritative: where it conflicts with
the task text, follow the answer.
Question: {question}
Answer: {answer}
"""

FACTS_BLOCK = """
These points were checked for logical consistency against the task text and its examples;
follow them unless the user's answer above says otherwise:
{facts}
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

DECISION_PATTERN = re.compile(r"DECISION[\s:*`]*(ASK|CODE)", re.IGNORECASE)
QUESTION_PATTERN = re.compile(r"QUESTION\s*:\s*(.+)", re.IGNORECASE)
PLACEHOLDER_PATTERN = re.compile(r"\{(\w+)\}")
ATOM_LINE = re.compile(r"^\W*ATOM\b\s*:?\s*(.*)$", re.IGNORECASE)
READINGS = re.compile(
    r"\|\s*(?:reading\s+)?A\s*[:)]\s*(.*?)\s*\|\s*(?:reading\s+)?B\s*[:)]\s*(.*?)\s*$", re.I
)
CHECK_LINE = re.compile(
    r"^\W*CHECK\b\s*:?\s*([A-Za-z_][\w-]*)\s*\|\s*A\s*:\s*(.*?)\s*\|\s*B\s*:\s*(.*?)\s*$",
    re.IGNORECASE,
)
EVIDENCE_LINE = re.compile(r"^\W*EVIDENCE\b\s*:?\s*(.+?)\s*=>\s*(.+?)\s*$", re.IGNORECASE)
LITERAL = re.compile(r"([A-Za-z_][\w-]*)\s*(?:==|=|:)\s*['\"`]?(A|B|TRUE|FALSE)\b", re.I)
PHRASE = re.compile(r"[\"“]([^\"“”]+)[\"”]")
CHECK_RESULT = re.compile(r"^CHK (\d+) (\d+) ([TFE])$", re.MULTILINE)
INLINE_EXAMPLE_OP = re.compile(r"\s*(?:==>|==|➞|=>|->|→|should return|returns|return)\s*", re.I)


def _fill(template: str, **fields: str) -> str:
    # One pass over the template's own placeholders: the inserted values (task text, model or
    # user output) routinely contain literal braces and must never be substituted into.
    return PLACEHOLDER_PATTERN.sub(lambda m: fields.get(m.group(1), m.group(0)), template)


# =================================================================================================
# Mechanical reading of the prompt (no LLM): signature stub and examples.
# =================================================================================================


def _balanced_parens(text: str, start: int) -> int | None:
    """Index just past the parenthesis group opening at text[start] == "(", skipping strings."""
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
            ok, args = _literal("(" + line[match.end() : end - 1] + ",)")
            if not ok or not isinstance(args, tuple):
                ok, args = (True, ()) if not line[match.end() : end - 1].strip() else (False, None)
            if not ok:
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


# =================================================================================================
# Formalization parsing
# =================================================================================================


def _norm_name(raw: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", raw.strip().strip("`'\"").lower()).strip("_")


def _clean_reading(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip().strip("`'\"").strip()
    text = text.rstrip(" .;?!")
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


def phrase_overlap(phrase: str, text: str, threshold: float = 0.6) -> bool:
    """Lenient check used only for wording a question (never for evidence): an exact quote, or
    a near-quote most of whose words appear in the text."""
    if quote_in_text(phrase, text):
        return True
    words = set(_tokens(phrase))
    return len(words) >= 3 and len(words & set(_tokens(text))) / len(words) >= threshold


def parse_formalization(response: str, prompt: str, entry_point: str) -> dict[str, Any] | None:
    """Returns {atoms, evidence, explicit_none}, or None if the response has no ATOM lines."""
    atoms: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    explicit_none = False
    lines = response.splitlines()

    for line in lines:
        match = ATOM_LINE.match(line)
        if not match:
            continue
        body = match.group(1).strip()
        if _norm_name(body) == "none":
            explicit_none = True
            continue
        readings = READINGS.search(body)
        if not readings:
            continue
        head = [field.strip() for field in body[: readings.start()].split("|")]
        name = _norm_name(head[0].split()[0]) if head and head[0].split() else ""
        if not name or name in by_name or name == "none" or len(atoms) >= MAX_ATOMS:
            continue
        rest = " | ".join(head[1:])
        phrase_match = PHRASE.search(rest)
        phrase = phrase_match.group(1).strip() if phrase_match else ""
        rest = PHRASE.sub(" ", rest)  # words inside the quoted phrase must not look like fields
        fields = [f.strip().upper() for f in rest.split("|")]
        kind = next((f for f in fields if f in KIND_RANK), None) or next(
            (k for k in KIND_RANK if re.search(rf"\b{k}\b", rest, re.I)), "VAGUE"
        )
        impact = "LOW" if "LOW" in fields or re.search(r"\bLOW\b", rest) else "HIGH"
        default = re.search(r"default\s*[:=]?\s*['\"`]?([AB])\b", rest, re.I)
        if phrase.lower().startswith("not stated") or not phrase_overlap(phrase, prompt):
            phrase = ""
        reading_a, reading_b = _clean_reading(readings.group(1)), _clean_reading(readings.group(2))
        if not reading_a or not reading_b or reading_a == reading_b:
            continue
        atom = {
            "name": name,
            "kind": kind,
            "impact": impact,
            "default": (default.group(1).upper() if default else "A"),
            "phrase": phrase[:MAX_QUOTE_LENGTH],
            "A": reading_a,
            "B": reading_b,
            "check_A": "",
            "check_B": "",
            "order": len(atoms),
        }
        atoms.append(atom)
        by_name[name] = atom

    if not atoms and not explicit_none:
        return None

    for line in lines:
        match = CHECK_LINE.match(line)
        if not match:
            continue
        atom = by_name.get(_norm_name(match.group(1)))
        if atom is None:
            continue
        for side, expr in (("A", match.group(2)), ("B", match.group(3))):
            expr = expr.strip().strip("`").strip()
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
        quote = match.group(1).strip().strip("“”\"'`").strip()
        literals = LITERAL.findall(match.group(2))
        if not quote or not literals:
            continue
        if not (quote_in_text(quote, prompt) or _norm_name(quote) == _norm_name(entry_point)):
            continue  # never let an unverifiable quote settle an atom
        clause = [
            (_norm_name(name), "A" if side.upper() in ("A", "TRUE") else "B")
            for name, side in literals
        ]
        if any(name not in by_name for name, _ in clause):
            continue  # dropping one literal would strengthen the clause: drop it all
        evidence.append({"quote": quote[:MAX_QUOTE_LENGTH], "clause": clause, "source": "text"})

    return {"atoms": atoms, "evidence": evidence, "explicit_none": explicit_none}


# =================================================================================================
# Grounding: run the atoms' checks on the prompt's own examples in the sandbox.
# =================================================================================================


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

    payload = repr(
        (list(params), [(ex["args"], ex["expected"]) for ex in examples], checks)
    ).encode()
    try:
        ast.literal_eval(payload.decode())  # the sandbox must be able to read it back
        output = env.exec_code(_fill(GROUNDING_SCRIPT, payload=base64.b64encode(payload).decode()))
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return []
    except LimitsExceededException:
        raise
    except Exception:
        return []

    results: dict[tuple[int, int], str] = {}
    for ci, ei, out in CHECK_RESULT.findall(output or ""):
        results[(int(ci), int(ei))] = out

    evidence = []
    for ei, example in enumerate(examples):
        verdict: dict[int, dict[str, str]] = {}
        for ci, (atom_i, side) in enumerate(slots):
            verdict.setdefault(atom_i, {})[side] = results.get((ci, ei), "E")
        clauses = []
        for atom_i, sides in verdict.items():
            # Only asymmetric verdicts count (one reading's check holds, the other's fails): a
            # single buggy check then cannot settle an atom on its own.
            a, b = sides.get("A"), sides.get("B")
            if a == "T" and b == "F":
                clauses.append([(atoms[atom_i]["name"], "A")])
            elif a == "F" and b == "T":
                clauses.append([(atoms[atom_i]["name"], "B")])
        for clause in clauses:
            evidence.append({"quote": example["quote"], "clause": clause, "source": "example"})
    return evidence


# =================================================================================================
# Reasoning: build the CNF with provenance groups, run DPLL, choose what to ask.
# =================================================================================================


def _priority(atom: dict[str, Any], core_hits: Counter) -> tuple:
    return (
        -core_hits.get(atom["name"], 0),
        0 if atom["impact"] == "HIGH" else 1,
        KIND_RANK.get(atom["kind"], 3),
        0 if atom["phrase"] else 1,
        atom["order"],
    )


def plan(formal: dict[str, Any], extra_evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure logic, no I/O. Returns {mode, target, quotes, facts, cores, consistent}."""
    atoms = formal["atoms"]
    index = {atom["name"]: i + 1 for i, atom in enumerate(atoms)}
    num_vars = len(atoms)
    phase = {index[a["name"]]: a["default"] == "A" for a in atoms}

    # One group per distinct source quote, text sources first (the MUS keeps the earliest).
    group_of: dict[tuple[str, str], int] = {}
    groups: list[list[list[int]]] = []
    labels: list[dict[str, str]] = []
    for ev in [*formal["evidence"], *extra_evidence]:
        key = (ev["source"], ev["quote"])
        if key not in group_of:
            group_of[key] = len(groups)
            groups.append([])
            labels.append({"quote": ev["quote"], "source": ev["source"]})
        lits = [index[name] if side == "A" else -index[name] for name, side in ev["clause"]]
        groups[group_of[key]].append(lits)

    cores, consistent = peel_cores(groups, num_vars)
    kept = [c for i in consistent for c in groups[i]]
    forced = backbone(kept, num_vars, phase) or {}
    contested = {abs(lit) for core in cores for i in core for c in groups[i] for lit in c}
    facts = []
    for atom in atoms:
        var = index[atom["name"]]
        if var in forced and var not in contested and atom["kind"] not in SUSPECT_KINDS:
            facts.append(atom["A"] if forced[var] else atom["B"])

    result: dict[str, Any] = {
        "mode": "code",
        "target": None,
        "quotes": [],
        "facts": facts,
        "cores": [[labels[i]["quote"] for i in core] for core in cores],
        "consistent": not cores,
    }

    if cores:
        core = cores[0]
        hits: Counter = Counter(abs(lit) for i in core for c in groups[i] for lit in c)
        core_hits = Counter({a["name"]: hits.get(index[a["name"]], 0) for a in atoms})
        in_core = [a for a in atoms if core_hits[a["name"]]]
        target = min(in_core, key=lambda a: _priority(a, core_hits))
        var = index[target["name"]]
        pro = [labels[i]["quote"] for i in core if any(var in c for c in groups[i])]
        con = [labels[i]["quote"] for i in core if any(-var in c for c in groups[i])]
        quotes = [pro[0], con[0]] if pro and con and pro[0] != con[0] else []
        result.update(mode="contradiction", target=target, quotes=quotes)
        result["facts"] = [f for f in facts if f not in (target["A"], target["B"])]
        return result

    askable = [a for a in atoms if index[a["name"]] not in forced or a["kind"] in SUSPECT_KINDS]
    if askable:
        target = min(askable, key=lambda a: _priority(a, Counter()))
        result.update(mode="ambiguity", target=target)
    return result


# =================================================================================================
# Questions, code checks and repair.
# =================================================================================================


def _short(quote: str) -> str:
    quote = re.sub(r"\s+", " ", quote).strip()
    return quote if len(quote) <= MAX_QUOTE_LENGTH else quote[: MAX_QUOTE_LENGTH - 3] + "..."


def build_question(decision: dict[str, Any], entry_point: str) -> str | None:
    target = decision["target"]
    if target is None:
        return None
    choice = f"Which is intended: {target['A']}, or {target['B']}?"
    if decision["mode"] == "contradiction" and len(decision["quotes"]) == 2:
        first, second = (_short(q) for q in decision["quotes"])
        lead = f'The task says "{first}" but also "{second}".'
    elif target["phrase"]:
        lead = f'The task says "{_short(target["phrase"])}".'
    else:
        lead = f"The task does not settle this for `{entry_point}`."
    return f"{lead} {choice}"[:MAX_QUESTION_LENGTH]


def atomic_question(question: str | None) -> str | None:
    """Keeps only the first question of a bundle ("...? Also, ...?")."""
    if not question:
        return None
    question = question.split("```", 1)[0].strip().strip("*`'\" ").strip()
    question = re.split(r"\s+(?:Also|Additionally|And also|Furthermore)\b[,:]?\s", question)[0]
    if "?" in question:
        question = question[: question.index("?") + 1]
    if len(question) < MIN_QUESTION_LENGTH:
        return None
    return question[:MAX_QUESTION_LENGTH]


def _parse_decision(response: str) -> str | None:
    match = DECISION_PATTERN.search(response)
    return match.group(1).upper() if match else None


def _parse_question(response: str) -> str | None:
    match = QUESTION_PATTERN.search(response)
    return atomic_question(match.group(1)) if match else None


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

    return code, None


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
    env: ClarificationEnvironment, problem: dict[str, Any], response: str, clarification: str
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
# Algorithm
# =================================================================================================


def _run_pipeline(
    env: ClarificationEnvironment, problem: dict[str, Any], state: dict[str, Any], hedge: bool
) -> None:
    prompt = problem["prompt"]
    entry_point = problem["entry_point"]
    params = find_stub_params(prompt, entry_point)
    rules = _fill(CODING_RULES, entry_point=entry_point)
    if params is None and hedge:
        rules += "\n" + _fill(HEDGE_RULE, entry_point=entry_point)
    state["rules"] = rules

    response = env.llm(
        _fill(
            FORMALIZE_TEMPLATE,
            prompt=prompt,
            entry_point=entry_point,
            rules=rules,
            signature_note=SIGNATURE_NOTE if params is None else "",
        )
    )
    state["candidate"] = _check_code(response, entry_point)[0] or ""
    own_decision, own_question = _parse_decision(response), _parse_question(response)

    formal = parse_formalization(response, prompt, entry_point)
    question: str | None = None
    facts: list[str] = []
    if formal is None or not formal["atoms"]:
        # Nothing to reason about: follow the model's own decision, as Pinpoint does.
        if own_decision == "ASK" and own_question:
            question = own_question
    else:
        examples = extract_examples(prompt, entry_point)
        extra = ground_examples(env, formal["atoms"], examples, params)
        decision = plan(formal, extra)
        state["plan"] = decision
        facts = decision["facts"]
        target = decision["target"]
        if decision["mode"] == "contradiction" or (
            target is not None
            and (target["impact"] == "HIGH" or target["kind"] in SUSPECT_KINDS or params is None)
        ):
            question = build_question(decision, entry_point) or own_question

    if question is None and own_decision != "ASK" and state["candidate"] and not facts:
        state["candidate"] = _finalize(env, problem, response, "") or state["candidate"]
        return

    answer = None
    if question and env.can_ask():
        try:
            answer = env.ask_human(question)
        except TooManyQuestionException:
            answer = None
    state["question"], state["answer"] = question, answer

    clarification = (
        _fill(CLARIFICATION_BLOCK, question=question, answer=answer) if question and answer else ""
    )
    facts_block = (
        _fill(FACTS_BLOCK, facts="\n".join(f"- {fact}" for fact in facts)) if facts else ""
    )
    state["clarification"] = clarification + facts_block
    code_response = env.llm(
        _fill(
            CODE_TEMPLATE,
            prompt=prompt,
            clarification=clarification,
            facts=facts_block,
            rules=rules,
        )
    )
    state["candidate"] = _check_code(code_response, entry_point)[0] or state["candidate"]
    state["candidate"] = (
        _finalize(env, problem, code_response, state["clarification"]) or state["candidate"]
    )


class LAASeR_FormalDPLL(ClarificationAlgorithmBase):
    DEFAULT_CONFIG = {"signature_hedge": True}

    def run(self, env: ClarificationEnvironment, problem: dict[str, Any]) -> str:
        state: dict[str, Any] = {"candidate": "", "clarification": "", "rules": ""}
        hedge = bool(self.config.get("signature_hedge", True))
        try:
            _run_pipeline(env, problem, state, hedge)
        except (TooManyQuestionException, LimitsExceededException):
            pass
        except Exception:
            # An unexpected failure must not cost the task: one plain coding attempt if nothing
            # usable exists yet.
            if not state["candidate"]:
                try:
                    response = env.llm(
                        _fill(
                            CODE_TEMPLATE,
                            prompt=problem["prompt"],
                            clarification=state["clarification"],
                            facts="",
                            rules=state["rules"]
                            or _fill(CODING_RULES, entry_point=problem["entry_point"]),
                        )
                    )
                    state["candidate"] = _check_code(response, problem["entry_point"])[0] or ""
                except Exception:
                    pass
        return state["candidate"]
