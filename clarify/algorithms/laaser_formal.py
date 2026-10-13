# SPDX-FileCopyrightText: 2026 Submitter <submitter@email.com>
#
# SPDX-License-Identifier: Open Source License like MIT, Apache 2.0, ...

"""Algorithm name.

LAASeR Formal algorithm.

Fase 3 challenger sixteen. Every earlier challenger (including `laaser_pinpoint.py` and
`laaser_pinpoint_sig.py`) decides whether a defect is worth asking about by trusting the model's
own self-rated `IMPACT: HIGH/LOW` judgment, or a textual rule about when to override it. This
variant instead *formalizes* each defect as a boolean variable ("atom": true = the first reading
is correct, false = the second) plus any logical relationships the task text itself states between
them, and runs a satisfiability check over that small propositional theory to mechanically decide:
- UNSAT (the theory, or the model's own best guess, is jointly contradictory) -> ask about it;
- AMBIGUOUS (more than one assignment satisfies the theory, disagreeing on some atom) -> ask about
  that atom;
- DETERMINED (exactly one satisfying assignment) -> code directly, handing the resolved facts to
  the coding call as settled context, no question spent.

No real SAT/SMT solver is available: Nagini (the formal verifier originally proposed) needs a JVM,
a Z3 binary and bundled Viper JARs, none of which exist in the fixed `ganler/evalplus` sandbox, and
`z3-solver` (the pure-pip Z3 bindings) was tested directly in that image and is not installed
either (`ModuleNotFoundError: No module named 'z3'`). This does not need one: with the small number
of atoms one task's defects ever produces (bounded defensively at `MAX_ATOMS`), brute-force
enumeration of every truth assignment is a correct, complete decision procedure for propositional
satisfiability, and it is a dozen lines of pure Python -- the same `env.exec_code` sandbox that
already runs `laaser_selfcheck.py`'s example-checking scripts runs this just as well.

This checks the *task specification* for logical consistency, before any code is written -- a
different axis from `laaser_selfcheck.py`/`laaser_pinpoint.py`, which verify *generated code*
against self-stated examples after the fact. It is not a retry of `laaser_pinpoint_sig.py` (a
textual "treat signature uncertainty as HIGH" rule, confirmed twice now to only partially work and
to inflate the ask rate): here nothing is decided by the model's own confidence, the ASK/CODE
decision is read off a mechanical SAT result.

Team: LAASeR - LIST
Team Members: Matias Brizzio, Jordi Cabot, Renzo Degiovanni
Main Contact: main.contact@email.com
"""

from __future__ import annotations

import ast
import re
from typing import Any

from clarify.baselines import ClarificationAlgorithmBase
from clarify.env import ClarificationEnvironment, LimitsExceededException, TooManyQuestionException
from clarify.runtime import _validate_and_parse_evalplus_result

MAX_REPAIR_ATTEMPTS = 2
MAX_QUESTION_LENGTH = 600
MAX_ATOMS = 16  # 2**16 brute-force assignments is still trivial; a bigger theory is never trusted

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

STEP 1 - FORMALIZE. List every place where the task does not uniquely determine the values that
`{entry_point}` must return: a contradiction between two statements (or a statement and an
example/signature/type hint), a vague word or phrase whose interpretation changes the output, a
missing rule (the arguments and their structure, the return type or format, a formula, a
threshold, a tie-break rule, the result for a special input), or an unusual extra requirement that
looks out of place. Requirements that tests cannot observe (time complexity, "no loops", "no
recursion", style, comments) are never defects.

Do not judge how likely or impactful each one is yourself. Instead, for every defect found,
introduce one boolean variable ("atom") standing for "the first reading is correct" (true) vs.
"the second reading is correct" (false), and write a Python dict literal, using Python's
`True`/`False`, starting with the literal word FORMALIZATION: immediately before the `{`:

FORMALIZATION: {{"defects": [{{"atom": "<short_lowercase_name>", "phrase": "<exact quoted text from the task, or: not stated>", "reading_true": "<what is true if this atom is True>", "reading_false": "<what is true if this atom is False>", "baseline": <your own best guess, True or False>}}, ...], "clauses": [["<atom_name>"], ["-<other_atom_name>", "<atom_name>"]]}}

Rules:
- One atom per defect. Name it with a short, descriptive, lowercase identifier.
- `clauses` states any logical relationship you can point to directly in the task text between
  atoms, or between an atom and a fixed value -- a clause is a list of literals (an atom name
  means it is True, that name prefixed with "-" means it is False; a clause is satisfied if any
  one of its literals is true). Never invent a clause just to force a particular outcome; only
  write one when the text itself states or implies it. If you cannot point to any such
  relationship, write `"clauses": []`.
- If there are no defects at all, write `{{"defects": [], "clauses": []}}`.
- The dict literal must be syntactically valid Python on its own, wherever it is wrapped.

STEP 2 - DECISION. Always write this, right after the dict, even when you are confident about
everything above. If `defects` is empty, write the line `DECISION: CODE` followed by the complete
implementation. Otherwise write the line `DECISION: ASK` followed by exactly one line:
QUESTION: <a real, atomic, concrete question about the single defect you judge most impactful>

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

FACTS_BLOCK_TEMPLATE = """
The following facts about the task were checked for logical consistency and are authoritative;
follow them exactly where the task text itself does not already fix the behaviour.
{facts}
""".strip()

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

SAT_SCRIPT_TEMPLATE = """
atoms = {atoms_repr}
clauses = {clauses_repr}
baseline = {baseline_repr}


def _satisfies(assignment, clauses):
    for clause in clauses:
        ok = False
        for lit in clause:
            name = lit[1:] if lit.startswith("-") else lit
            val = assignment.get(name, False)
            if lit.startswith("-"):
                val = not val
            if val:
                ok = True
                break
        if not ok:
            return False
    return True


n = len(atoms)
models = []
for bits in range(2 ** n):
    assignment = {atoms[i]: bool((bits >> i) & 1) for i in range(n)}
    if _satisfies(assignment, clauses):
        models.append(assignment)

if not models or baseline not in models:
    print("SAT_RESULT=UNSAT")
else:
    free = [a for a in atoms if len({m[a] for m in models}) > 1]
    if free:
        print("SAT_RESULT=AMBIGUOUS atoms=" + repr(free))
    else:
        print("SAT_RESULT=DETERMINED")
""".strip()

DECISION_PATTERN = re.compile(r"DECISION[\s:*`]*(ASK|CODE)", re.IGNORECASE)
QUESTION_PATTERN = re.compile(r"QUESTION\s*:\s*(.+)", re.IGNORECASE)
SAT_RESULT_PATTERN = re.compile(r"SAT_RESULT=(UNSAT|AMBIGUOUS|DETERMINED)(?:\s+atoms=(\[.*\]))?")
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
    return question[:MAX_QUESTION_LENGTH] if question else None


def _extract_balanced(text: str, open_char: str, close_char: str) -> str | None:
    """First top-level `open_char ... close_char` span in text, skipping quoted-string contents."""
    start = text.find(open_char)
    if start == -1:
        return None
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
        elif ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
        i += 1
    return None


def _parse_formalization(response: str) -> dict[str, Any] | None:
    """Returns {atoms, clauses, baseline, readings, phrases}, or None if unreadable."""
    # The "FORMALIZATION:" marker is prompted for but not required: models asked for "a single
    # dict literal with no other text" often take that literally and omit the marker itself, so
    # requiring it caused most real formalizations to be silently discarded. Scan the whole
    # response for the first top-level `{...}` instead, wherever it appears.
    snippet = _extract_balanced(response, "{", "}")
    if snippet is None:
        return None
    try:
        parsed = ast.literal_eval(snippet)
    except (ValueError, SyntaxError, RecursionError):
        return None
    if not isinstance(parsed, dict):
        return None

    defects = parsed.get("defects")
    raw_clauses = parsed.get("clauses")
    if not isinstance(defects, list) or not isinstance(raw_clauses, list):
        return None

    atoms: list[str] = []
    baseline: dict[str, bool] = {}
    readings: dict[str, tuple[str, str]] = {}
    phrases: dict[str, str] = {}
    for defect in defects:
        if not isinstance(defect, dict):
            continue
        atom = defect.get("atom")
        if not isinstance(atom, str) or not atom or atom in atoms or atom.startswith("-"):
            continue
        atoms.append(atom)
        baseline[atom] = bool(defect.get("baseline", False))
        readings[atom] = (str(defect.get("reading_true", "")), str(defect.get("reading_false", "")))
        phrases[atom] = str(defect.get("phrase", "not stated"))

    atom_set = set(atoms)
    clauses: list[list[str]] = []
    for clause in raw_clauses:
        if not isinstance(clause, list):
            continue
        literals = [lit for lit in clause if isinstance(lit, str)]
        if literals and all(
            (lit[1:] if lit.startswith("-") else lit) in atom_set for lit in literals
        ):
            clauses.append(literals)

    return {
        "atoms": atoms,
        "clauses": clauses,
        "baseline": baseline,
        "readings": readings,
        "phrases": phrases,
    }


def _build_question(atom: str, formalization: dict[str, Any]) -> str:
    phrase = formalization["phrases"].get(atom, "not stated")
    true_text, false_text = formalization["readings"].get(atom, ("", ""))
    if not true_text and not false_text:
        question = f"Regarding {atom.replace('_', ' ')}: what is the correct behaviour here?"
    elif phrase and phrase != "not stated":
        question = f'The task says "{phrase}" -- is it that {true_text}, or that {false_text}?'
    else:
        question = f"The task never states this: is it that {true_text}, or that {false_text}?"
    return question[:MAX_QUESTION_LENGTH]


def _build_facts_block(formalization: dict[str, Any]) -> str:
    lines = []
    for atom in formalization["atoms"]:
        value = formalization["baseline"].get(atom, False)
        true_text, false_text = formalization["readings"].get(atom, ("", ""))
        text = true_text if value else false_text
        if text:
            lines.append(f"- {text}")
    if not lines:
        return ""
    return _fill(FACTS_BLOCK_TEMPLATE, facts="\n".join(lines))


def _run_sat_check(env: ClarificationEnvironment, formalization: dict[str, Any]) -> dict[str, Any]:
    atoms = formalization["atoms"]
    full_baseline = {atom: formalization["baseline"].get(atom, False) for atom in atoms}
    script = _fill(
        SAT_SCRIPT_TEMPLATE,
        atoms_repr=repr(atoms),
        clauses_repr=repr(formalization["clauses"]),
        baseline_repr=repr(full_baseline),
    )
    output = env.exec_code(script)
    match = SAT_RESULT_PATTERN.search(output)
    if not match:
        return {"result": None, "atoms": []}

    free_atoms: list[str] = []
    if match.group(1) == "AMBIGUOUS" and match.group(2):
        try:
            parsed = ast.literal_eval(match.group(2))
            if isinstance(parsed, list):
                free_atoms = [a for a in parsed if isinstance(a, str)]
        except (ValueError, SyntaxError):
            free_atoms = []
    return {"result": match.group(1), "atoms": free_atoms}


def _fallback_decision(response: str, entry_point: str) -> tuple[str, str | None]:
    """Returns ("CODE", code) or ("ASK", question) from the response's own DECISION/QUESTION lines."""
    decision = _parse_decision(response)
    fallback_question = _parse_question(response)
    if decision == "CODE" or (decision is None and fallback_question is None):
        return "CODE", _check_code(response, entry_point)[0] or ""
    return "ASK", fallback_question


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


class LAASeR_Formal(ClarificationAlgorithmBase):
    def run(self, env: ClarificationEnvironment, problem: dict[str, Any]) -> str:
        prompt = problem["prompt"]
        entry_point = problem["entry_point"]
        rules = _rules(entry_point)
        candidate = ""

        try:
            response = env.llm(
                _fill(FORMALIZE_TEMPLATE, prompt=prompt, entry_point=entry_point, rules=rules)
            )
            formalization = _parse_formalization(response)
            usable = (
                formalization is not None
                and bool(formalization["atoms"])
                and len(formalization["atoms"]) <= MAX_ATOMS
            )
            sat_result = _run_sat_check(env, formalization) if usable else None

            question: str | None = None
            extra_context = ""

            if sat_result and sat_result["result"] in ("UNSAT", "AMBIGUOUS"):
                target_pool = sat_result["atoms"] or [formalization["atoms"][0]]
                atom = next(
                    (a for a in formalization["atoms"] if a in target_pool),
                    formalization["atoms"][0],
                )
                question = _build_question(atom, formalization)
            elif sat_result and sat_result["result"] == "DETERMINED":
                extra_context = _build_facts_block(formalization)
            else:
                decision, payload = _fallback_decision(response, entry_point)
                if decision == "CODE":
                    candidate = payload or ""
                    return _finalize(env, problem, response, "") or candidate
                question = payload

            answer = None
            if question and env.can_ask():
                try:
                    answer = env.ask_human(question)
                except TooManyQuestionException:
                    answer = None

            clarification = _clarification_block(question, answer) or extra_context
            code_response = env.llm(
                _fill(CODE_TEMPLATE, prompt=prompt, clarification=clarification, rules=rules)
            )
            candidate = _check_code(code_response, entry_point)[0] or candidate
            candidate = _finalize(env, problem, code_response, clarification) or candidate
        except (TooManyQuestionException, LimitsExceededException):
            pass
        except Exception:
            # Never lose an already-usable candidate to an unexpected failure.
            pass

        return candidate
