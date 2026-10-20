# SPDX-FileCopyrightText: 2026 Your Name <you@example.org>
#
# SPDX-License-Identifier: MIT

"""SpecGuidedClarification (v5).

Fixes the function signature first (test-author view: plausible calls, arity and kinds), asking an open
question on serious doubt. Then formalises the task (literal versus classic reading, name-word coverage,
uncertainty ledger) and asks open, atomic questions about the most uncertain decisions. Weak answers are
re-asked once. The implementation is checked for adherence and verified with Nagini when it is installed.

Team: Your Team
Team Members: Member 1
Main Contact: you@example.org
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from clarify.baselines.base import ClarificationAlgorithmBase
from clarify.env import ClarificationEnvironment

try:
    from clarify.env import TooManyQuestionException
except ImportError:  # the SDK docstring spells it TooManyQuestionsException
    from clarify.env import TooManyQuestionsException as TooManyQuestionException


# --------------------------------------------------------------------------- prompts

QUALITY_RUBRIC = """You also judge whether the task description is CORRECT. A programming-task description specifies
a coding problem: behavior, inputs/outputs, constraints and examples. Decide whether it is accurate, consistent and
internally coherent. 
The description already contains everything the user confirmed: a point it states is settled. If it rejects a proposed shape, your signature MUST differ from it.
Evaluate along:
1. Accuracy: trace every given example against the stated rule or formula. If an example's output contradicts what the
   stated logic would produce, the description is INCORRECT (correctness issue); this overrides other considerations.
2. Completeness: does it omit a constraint, filter or condition that would change which inputs qualify or how the
   output is computed (dropped exclusion criteria, missing edge-case rule, missing output type, missing threshold)?
3. Consistency: do examples, constraints and prose agree with each other?
4. Clarity/Ambiguity: would competent programmers following standard conventions (0-indexing, usual tie-breaking,
   the natural reading of the function name) converge on the same behavior?
Key detection rules (apply explicitly):
- Vague-placeholder red flag: phrases like "a certain type of X", "a certain number", "handles it in a standard way",
  "do something with", "some way" — especially."""

SIGNATURE_SYSTEM = """You determine the exact Python signature of the function `entry_point` from a task description.

Background: descriptions are short, deliberately blurred versions of classic exercises. A hidden test-suite calls
the function with fixed positional arguments. A wrong number of arguments, or a wrong kind of argument (one list
versus two lists, a list versus a single number, a flat list versus a list of pairs), fails every test.

Work like the author of the test-suite:
1. Write three different plausible test calls, as in `assert f(<args>) == <expected>`. Give only the argument lists,
   as Python literals. They help you think; they are not used to decide whether to ask.
2. From the calls and the description, choose the most probable signature.
3. Judge the description, for the inputs and the return value ONLY.

""" + QUALITY_RUBRIC + """

Reply with one ```json block:
{"calls": ["[arg1, arg2]", "[arg1, arg2]", "[arg1, arg2]"],
 "signature": "def f(a: List[int], b: int) -> bool:",
 "assessment": {"reasoning": "<max 60 words>", "verdict": "correct" | "incorrect",
                "issue_type": "none" | "ambiguity" | "incompleteness" | "contradiction" | "correctness"},
 "alternatives": ["def f(...) -> ...:"]}

Rules:
- Fully annotate with typing names (List, Dict, Tuple, Optional...). Keep the given entry_point name.
- Read every noun in the description and in the function name as evidence about the inputs: "between X" or a plural
  such as "lists" means separate operands; "pairs" or "tuples" means a collection of tuples; a geometric solid needs
  all the dimensions its volume needs; "matrix" means a list of lists; "recursive" or "nested" means nested data;
  "word", "text" or "string" means a string.
- Do not minimise and do not maximise the number of parameters: choose what the description implies. A fixed
  threshold stays a constant only if the description gives no sign that the caller supplies it.
- USER CLARIFICATIONS settle everything they cover. If an answer rejects a proposed shape, your signature MUST differ
  from it. Answers marked partial or evasive must not be relied on.
- verdict is "incorrect" only if a test author could reasonably choose a different number or kind of arguments, or a
  different return form. Then alternatives lists those competing signatures. If the verdict is "correct",
  alternatives is []. issue_type is "none" if and only if the verdict is "correct"."""

QUESTION_SYSTEM = """You write ONE clarification question for a user who knows the intended behavior of a Python
function but cannot show you the tests. Unnecessary questions are penalized, so ask only for the single missing fact.

You get the task with earlier clarifications, an assessment of the description (issue type and reasoning), and the
decision that is still open (what you assumed, the alternatives, and sometimes an input on which they differ).

Choose the form by issue type:
- incompleteness: ask for the missing element. Example: "What condition must a word satisfy to count as long?"
- ambiguity: name the competing readings briefly and neutrally, without preferring one.
  Example: "Which of these should the function return: the count of matches or the matches themselves?"
- contradiction: quote the two conflicting statements. Example: "Which is correct: A or B?"
- correctness: an example contradicts the rule, so ask what the call must return.
  Example: "What should f([1, 2]) return?"
If a witness input is given and one value settles the point, "What should f(<witness>) return?" is also good.
If the topic is "signature", ask how many arguments the function takes and of what kind, naming the candidates.

Rules: one sentence, exactly one question mark, beginning with What, Which or How. Never yes/no. Never mark one
reading as the default. Do not mention tests or implementation techniques. Do not repeat an earlier question; if the
user already answered partially, ask for the missing part from another angle.
Reply with the question only."""

FORMAL_SYSTEM = """You are a requirements analyst. Turn a task description (plus any user clarifications) into a
precise specification, judge the quality of the description, and list what is still uncertain.

Background: the description is a short, deliberately blurred version of a classic programming exercise. The exact
criterion or formula, constants, which items are affected, the form of the return value or the counting rule may
have been removed. The simplest reading is NOT automatically the intended one.

The SIGNATURE is FIXED and settled. Do not change it, question it or list uncertainties about it.

""" + QUALITY_RUBRIC + """

Reply with one ```json block:
{"assessment": {"reasoning": "<max 80 words>", "verdict": "correct" | "incorrect",
                "issue_type": "none" | "ambiguity" | "incompleteness" | "contradiction" | "correctness"},
 "readings": {"literal": "what the description says, read word by word",
              "classic": "the standard version of this exercise as you remember it, or null",
              "differ": true, "difference": "what differs between them, or null"},
 "rule": "1-3 sentences: exactly what the function computes and returns",
 "requires": ["expr"], "ensures": ["expr"],
 "examples": [{"args": "[a1, b1]", "expected": "value"}],
 "uncertainties": [{"category": "output|semantics|constant|edge",
                    "issue_type": "ambiguity|incompleteness|contradiction|correctness",
                    "assumed": "...", "alternatives": ["...", "..."],
                    "witness": "arguments of one call as a Python list literal on which the alternatives differ, or null",
                    "confidence": 0.0, "impact": "high|low"}]}

Rules:
- assessment judges the description together with the user clarifications, ignoring the signature. issue_type is
  "none" if and only if the verdict is "correct". If you list a high-impact uncertainty with confidence below 0.6,
  the verdict cannot be "correct".
- Account for every content word of the function name and of the description. A word that your rule does not use
  (for example "lowercase", "dirty", "special", "long", or a name part such as "Occ") is an uncertainty.
- Compare the verb of the description with the prefix of the name. is_/check/test suggest a boolean, find/get/
  compute/count suggest a value. If they disagree, the OUTPUT form is uncertain.
- readings.differ is true if the classic version would give a different result from the literal reading on an input
  that an ordinary test would try. If differ is true, include a matching uncertainty with confidence 0.5 or less.
- rule: follow the clarifications; where nothing settles a point, follow the literal reading.
- Statements in the description are settled; never list them as uncertain. For a point listed under 'POINTS THE USER COULD NOT SETTLE', take the standard reading with confidence 1.0.
- requires/ensures: No method calls (no .count, .index, .bit_count), no bin, str or format; use only arithmetic, comparisons, len, sum, min, max, sorted, set, all, any, abs, Result(), Old(x) and Implies(a, b)..
- examples: ONLY input/output pairs literally given in the description or derivable with certainty from the
  clarifications. Never compute your own. Use [] if there are none.
- uncertainties: each decision where a competent developer could choose differently and an ordinary unit test would
  notice. issue_type: incompleteness = a criterion, constant or output form is missing; ambiguity = several readings
  fit; contradiction = two statements disagree; correctness = a given example contradicts the stated rule.
  confidence = probability that your assumption matches what the test-suite expects. Use 0.6 or less whenever the
  description names no criterion, formula or constant for something the function must decide.
  Order by importance: output, semantics, constant, edge.
- Do NOT list: the signature, int versus float, mutating versus returning, naming, performance, style, invalid input."""

IMPL_SYSTEM = """You implement a Python function from a task description, a rule, a signature, a contract and user
clarifications. Reply with exactly one ```python block with the complete code (imports included, standard library
only). Rules:
- Exactly the given function name and parameters. Never add, remove or rename parameters. If a constant is not
  specified, hard-code the most standard value.
- The description is authoritative, including every sentence added from user answers. Do not add behaviour nobody asked for. No assert statements and no
  isinstance checks.
- No printing, no input(). Do not mutate the arguments.
- Use typing names (List, Dict, Tuple, Optional) and import them from typing.
- Be efficient: no loop proportional to the input VALUE; use closed forms, logarithmic bounds or early termination.
  Avoid deep recursion on long inputs.
- Python pitfalls: int.bit_count() and bin() ignore the sign, so for a single-set-bit test on a possibly negative
  integer use x != 0 and x & (x - 1) == 0. To split text into words use re.findall(r"\\b\\w+\\b", text), not
  str.split(), unless whitespace splitting is requested. If the function is described as recursive or nested, handle
  nested lists."""

CHECK_SYSTEM = """Check code against the requirements. List violations of EXPLICIT statements in the description, the
clarifications or the rule: wrong number, order or type of parameters, extra parameters that nobody asked for,
wrong return form, statements of the description that the code ignores. Do not flag style or unverifiable guesses.
Reply with one ```json block: {"violations": ["..."]} (empty list if none)."""

DIAG_SYSTEM = """Nagini could not verify a candidate implementation against its specification. Decide who is wrong.
The Nagini output gives the violated clause and a source line. Line numbers refer to a program in which the
Requires/Ensures lines were inserted at the top of the function body. The specification was written by a model and
may itself be wrong or too strong. Reason about the rule step by step before deciding.
The signature is fixed and must not change.
Reply with one ```json block:
{"analysis": "short reasoning", "verdict": "impl_bug" | "spec_bug" | "unclear",
 "requires": [...], "ensures": [...], "question": null}
- impl_bug: the candidate is wrong. Also add one ```python block with the complete corrected code.
- spec_bug: the contract is wrong. Give the full replacement "requires" and "ensures".
- unclear: the task text does not settle it AND asking is allowed. Give ONE open question (What/Which/How) that does
  not mention tests or implementation details and is not about the signature.
If asking is not allowed you MUST pick impl_bug or spec_bug, following the most plausible reading of the task."""

OPEN_SYSTEM = """Rewrite the text as ONE open question (one sentence, exactly one question mark) that begins with
What, Which or How and asks the user to state the single missing fact. Do not propose a default reading, do not ask
yes/no, do not offer several topics, do not mention tests. Reply with the question only."""

REPHRASE_SYSTEM = """The user gave a partial or evasive answer to a clarifying question. Write ONE different, shorter,
open question (one sentence, exactly one question mark, beginning with What, Which or How) that asks for the same
missing fact from another angle, for example by asking what the function returns for a small concrete input. Do not
mention tests. Reply with the question only."""


PROBE_SYSTEM = """You write call arguments that will be used to compare two implementations of the same function.
You do not know the expected results and must not compute them.
You get the task, the signature and the user clarifications.
Reply with one ```json block: {"inputs": ["[arg1, arg2]", "[arg1, arg2]"]}
- 8 to 12 small inputs. Each is a Python literal list with exactly the arguments of the signature. Deterministic.
- Typical cases first. Then the points on which two competent developers could differ: negative numbers, zero,
  empty collections, duplicates, ties, repeated characters, upper and lower case, punctuation, nested data, a small
  and a medium value.
- Copy any example given in the task or in the clarifications exactly.
- Respect what the task and the clarifications establish about valid values. No invalid types."""

JUDGE_DIFF_SYSTEM = """Two implementations of the same Python function were written independently from the same task.
They return different results on one call. Decide whether the user's clarifications already settle which one is
right. If not, write ONE question for the user.
Reply with one ```json block:
{"reasoning": "<max 50 words>", "settled": true | false, "right": "A" | "B" | "unknown",
 "issue_type": "ambiguity" | "incompleteness" | "contradiction" | "correctness", "question": null}
- settled is true only if the task text or an explicit user clarification fixes the result of this call. Partial or
  evasive answers settle nothing. Then right says which result is correct, and question is null.
- Otherwise settled is false, right is "unknown", and question is one sentence with exactly one question mark,
  beginning with What, Which or How, never yes/no. It asks for the intended behaviour as a rule. Use this call as an
  example only if it helps, and name the competing behaviours neutrally. Do not show code, do not mention tests or
  implementations, and do not mark either behaviour as the default.
  Forms: ambiguity "Which of these should the function do: X or Y?"; incompleteness "What ... ?";
  correctness "What should f(args) return?"."""

EVOLVE_SYSTEM = """You maintain the text of a programming-task description. A user just answered a clarification
question. Rewrite the description so that it states the fact the answer establishes, as if the original author had
written it.

Rules:
- Keep everything the answer does not contradict: wording, examples, the function name. Keep the same format (if the
  description is a docstring, return a docstring).
- Add only what the answer states. No default readings, no examples you computed, no implementation hints, no
  guesses about what the answer leaves open.
- Put the fact in its natural place: a sentence for the criterion, the inputs or the return form. If the answer
  replaces an earlier statement, replace it; never keep two conflicting statements.
- A fact about a criterion is not a new argument. Add a parameter to the description only if the answer says that the
  caller supplies it.
- If the answer states the arguments, write "The function takes ..." with their number and kinds.
- If the answer is partial, evasive or states no fact, set changed to false and return the description unchanged.
- The description grows by at most two sentences per answer.

Reply with one ```json block:
{"changed": true, "fact": "the fact the answer establishes, one sentence, or null",
 "description": "the full rewritten description"}"""

# --------------------------------------------------------------------------- helpers

def _extract_json(text: str) -> dict[str, Any] | None:
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S)
    cand = m.group(1) if m else None
    if cand is None:
        s, e = text.find("{"), text.rfind("}")
        if s == -1 or e <= s:
            return None
        cand = text[s : e + 1]
    try:
        out = json.loads(cand)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


def _extract_code(text: str) -> str | None:
    blocks = re.findall(r"```(?:python|py)\s*\n(.*?)```", text, re.S)
    return max(blocks, key=len).strip() if blocks else None


def _llm(env: ClarificationEnvironment, system: str, user: str) -> str:
    return env.llm([{"role": "system", "content": system}, {"role": "user", "content": user}])


def _llm_json(env: ClarificationEnvironment, system: str, user: str, tries: int = 2) -> dict[str, Any]:
    for _ in range(tries):
        out = _extract_json(_llm(env, system, user))
        if out is not None:
            return out
    return {}


def _valid_expr(src: Any) -> bool:
    if not isinstance(src, str) or not src.strip():
        return False
    try:
        ast.parse(src, mode="eval")
        return True
    except SyntaxError:
        return False


def _literal(src: Any) -> Any:
    return ast.literal_eval(src) if isinstance(src, str) else src

def _nagini_safe(src: str) -> bool:
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError:
        return False
    return not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) for n in ast.walk(tree))
def _clean_spec(out: dict[str, Any]) -> dict[str, Any]:
    """Keep only valid, non-degenerate clauses and literal examples."""
    req = [r for r in out.get("requires") or [] if _valid_expr(r) and r.strip() != "False" and _nagini_safe(r)]
    ens = [e for e in out.get("ensures") or [] if _valid_expr(e) and e.strip() != "True" and _nagini_safe(e)]
    examples = []
    for ex in out.get("examples") or []:
        try:
            args, exp = _literal(ex["args"]), _literal(ex["expected"])
            if isinstance(args, (list, tuple)):
                examples.append((list(args), exp))
        except (ValueError, SyntaxError, KeyError, TypeError):
            continue
    return {"requires": req, "ensures": ens, "examples": examples}


def _parse_signature(sig: Any, entry: str) -> dict[str, Any] | None:
    if not isinstance(sig, str):
        return None
    sig = sig.strip().rstrip(":") + ":"
    try:
        fn = ast.parse(sig + "\n    pass").body[0]
    except SyntaxError:
        return None
    if not isinstance(fn, ast.FunctionDef) or fn.name != entry:
        return None
    kinds = []
    for a in fn.args.args:
        ann = ast.unparse(a.annotation) if a.annotation is not None else ""
        ann = re.sub(r"\btyping\.", "", ann).replace(" ", "").lower()
        kinds.append(re.sub(r"\bfloat\b", "int", ann))
    return {"text": sig, "params": [a.arg for a in fn.args.args], "kinds": kinds}


def _header_from_prompt(prompt: str, entry: str) -> str | None:
    try:
        tree = ast.parse(prompt)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == entry:
            return ast.unparse(node).splitlines()[0]
    return None


def _code_params(code: str, entry: str) -> list[str] | None:
    try:
        for n in ast.parse(code).body:
            if isinstance(n, ast.FunctionDef) and n.name == entry:
                return [a.arg for a in n.args.args]
    except SyntaxError:
        pass
    return None


def _looks_specified(prompt: str) -> bool:
    """Prompts with examples or substantial text get a stricter asking gate."""
    return bool(re.search(r">>>|\bassert\b|[Ee]xample|\bexpected\b|=>|->\s*[\[\(\d'\"]", prompt)) or len(prompt) > 400


def _similar(a: str, b: str) -> bool:
    ta, tb = set(re.findall(r"\w+", a.lower())), set(re.findall(r"\w+", b.lower()))
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) > 0.6


def _conf(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 1.0


_EVASIVE = re.compile(r"can'?t (specify|clarify|say)|cannot (specify|clarify|say)|unable to|don'?t know|not sure|no further", re.I)


def _weak_answer(answer: str) -> bool:
    """Truncated, very short or evasive answers carry little information."""
    a = (answer or "").strip()
    return len(a) < 12 or not re.search(r"[.!?)\"'`\]\d]$", a) or bool(_EVASIVE.search(a))


def _one_question(text: str) -> str:
    text = " ".join(text.strip().strip("`").split())
    return text[: text.index("?") + 1] if "?" in text else text

_YES_NO_START = re.compile(r"^\s*(should|does|do|is|are|can|will|would|has|have|did)\b", re.I)


def _open(env: ClarificationEnvironment, q: str) -> str:
    """Questions must be open (What/Which/How) and single: yes/no and compound ones are rewritten."""
    q = " ".join(q.split())
    compound = q.count("?") > 1 or len(q) > 240
    if not _YES_NO_START.match(q) and not compound:
        return q
    out = _one_question(_llm(env, OPEN_SYSTEM, q))
    return out if "?" in out and len(out) >= 10 else _one_question(q)

def _fmt_spec(f: dict[str, Any]) -> str:
    lines = [f"Rule: {f['rule']}"] if f.get("rule") else []
    lines += [f"Requires({r})" for r in f["requires"]] + [f"Ensures({e})" for e in f["ensures"]]
    lines += [f"Example: f(*{a!r}) == {e!r}" for a, e in f["examples"]]
    return "\n".join(lines) or "(no contract)"


ISSUES = ("ambiguity", "incompleteness", "contradiction", "correctness")
_ISSUE_RANK = {"contradiction": 0, "correctness": 0, "incompleteness": 1, "ambiguity": 2}


def _assessment(raw: Any) -> dict[str, str]:
    """Normalise the judge fields. A missing assessment counts as 'incorrect', so behaviour falls back to v5."""
    if not isinstance(raw, dict):
        return {"verdict": "incorrect", "issue_type": "incompleteness", "reasoning": ""}
    verdict = "incorrect" if str(raw.get("verdict", "")).lower() == "incorrect" else "correct"
    issue = str(raw.get("issue_type", "")).lower()
    if verdict == "correct":
        issue = "none"
    elif issue not in ISSUES:
        issue = "incompleteness"
    return {"verdict": verdict, "issue_type": issue, "reasoning": str(raw.get("reasoning", ""))[:600]}


def _sig_differs(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return len(a["params"]) != len(b["params"]) or a["kinds"] != b["kinds"]


def make_question(s: _Session, topic: str, assessment: dict[str, str], item: dict[str, Any]) -> str | None:
    """One question shaped by the issue type and the judge's reasoning."""
    prior = "\n".join(f"- {q}" for q, _ in s.qa) or "(none)"
    user = (
        s.context()
        + f"\nTOPIC: {topic}\nISSUE TYPE: {item.get('issue_type') or assessment['issue_type']}\n"
        + f"ASSESSMENT: {assessment['reasoning'] or '(none)'}\n"
        + f"OPEN DECISION:\n{json.dumps(item, ensure_ascii=False)}\n\nEARLIER QUESTIONS:\n{prior}\n"
    )
    q = _one_question(_llm(s.env, QUESTION_SYSTEM, user))
    if "?" not in q or len(q) < 10 or any(_similar(q, a) for a, _ in s.qa):
        return None
    return q

def _overlap(a: str, b: str) -> float:
    ta, tb = set(re.findall(r"\w+", a.lower())), set(re.findall(r"\w+", b.lower()))
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def _evolution_ok(old: str, new: Any, entry: str) -> bool:
    """Reject rewrites that drop the function name or an example, shrink or balloon the text, or replace it."""
    if not isinstance(new, str) or not new.strip():
        return False
    new = new.strip()
    if entry in old and entry not in new:
        return False
    if len(new) > len(old) + 500 or len(new) < 0.6 * len(old):
        return False
    keep = [ln.strip() for ln in old.splitlines() if re.search(r">>>|\bassert\b|==|=>", ln)]
    if any(ln not in new for ln in keep):
        return False
    return _overlap(old, new) >= 0.4


class _Session:
    """Per-problem state: the evolving task description, question budget and Q/A log."""

    def __init__(self, env: ClarificationEnvironment, problem: dict[str, Any], max_questions: int, evolve: bool = True):
        self.env = env
        self.prompt: str = problem["prompt"]  # original, never modified
        self.entry: str = problem["entry_point"]
        self.max_q = max_questions
        self.evolve = evolve
        self.desc: str = self.prompt.strip()  # working copy, rewritten after informative answers
        self.versions: list[str] = [self.desc]
        self.facts: list[str] = []
        self.qa: list[tuple[str, str]] = []

    def can_ask(self) -> bool:
        return len(self.qa) < self.max_q and bool(self.env.can_ask())

    def ask(self, question: str) -> bool:
        if not self.can_ask():
            return False
        try:
            answer = self.env.ask_human(question)
        except TooManyQuestionException:
            return False
        self.qa.append((question, answer))
        self._integrate(question, answer)
        return True

    def _integrate(self, question: str, answer: str) -> None:
        """Fold an informative answer into the working description."""
        if not self.evolve or _weak_answer(answer):
            return
        user = f"CURRENT DESCRIPTION:\n{self.desc}\n\nENTRY POINT: {self.entry}\n\nQUESTION: {question}\nANSWER: {answer}\n"
        out = _llm_json(self.env, EVOLVE_SYSTEM, user, tries=1)
        fact = out.get("fact") if isinstance(out.get("fact"), str) and out["fact"].strip() else None
        if out.get("changed") is False and not fact:
            return
        fact = fact or " ".join(answer.split())
        new = out.get("description")
        new = new.strip() if _evolution_ok(self.desc, new, self.entry) else self.desc + "\n" + fact
        self.facts.append(fact)
        self.desc = new
        self.versions.append(new)

    def ask_robust(self, question: str) -> bool:
        """Ask; if the answer is weak and budget remains, ask once more from another angle."""
        if not self.ask(question):
            return False
        if _weak_answer(self.qa[-1][1]) and self.can_ask():
            alt = _one_question(_llm(self.env, REPHRASE_SYSTEM, f"Question: {question}\nAnswer: {self.qa[-1][1]!r}"))
            if "?" in alt and len(alt) >= 10 and not _similar(alt, question):
                self.ask(alt)
        return True

    def context(self) -> str:
        s = f"TASK DESCRIPTION:\n{self.desc}\n\nENTRY POINT: {self.entry}\n"
        if not self.evolve:  # v5 behaviour: clarifications appended
            if self.qa:
                lines = []
                for q, a in self.qa:
                    flag = "  (partial or evasive answer: do not rely on it)" if _weak_answer(a) else ""
                    lines.append(f"Q: {q}\nA: {a}{flag}")
                s += "\nUSER CLARIFICATIONS (authoritative):\n" + "\n".join(lines) + "\n"
            return s
        open_pts = [q for q, a in self.qa if _weak_answer(a)]
        if open_pts:
            s += (
                "\nPOINTS THE USER COULD NOT SETTLE (use the standard reading, confidence 1.0, do not ask again):\n"
                + "\n".join(f"- {q}" for q in open_pts) + "\n"
            )
        return s
# --------------------------------------------------------------------------- stage 1: signature

def _sig_samples(s: _Session, n: int = 2) -> list[tuple[dict[str, Any], dict[str, str], list[dict[str, Any]]]]:
    samples = []
    for _ in range(n):
        out = _llm_json(s.env, SIGNATURE_SYSTEM, s.context(), tries=1)
        parsed = _parse_signature(out.get("signature"), s.entry)
        if not parsed:
            continue
        assess = _assessment(out.get("assessment"))
        rivals: list[dict[str, Any]] = []
        if assess["verdict"] == "incorrect":
            for a in out.get("alternatives") or []:
                pa = _parse_signature(a, s.entry)
                if pa and _sig_differs(parsed, pa):
                    rivals.append(pa)
        samples.append((parsed, assess, rivals))
    return samples

def _signature_question(entry: str, sigs: list[dict[str, Any]]) -> str:
    texts = []
    for p in sigs:
        t = p["text"].rstrip(":")
        if t not in texts:
            texts.append(t)
    hint = f" (for example `{texts[0]}` or `{texts[1]}`)" if len(texts) > 1 else ""
    return f"What arguments does `{entry}` take{hint}: how many, and what kind of value is each one?"


def tool_extract_signature(s: _Session, header: str | None, max_sig_questions: int) -> dict[str, Any]:
    """Ask only when a rival signature with another number or kind of arguments is plausible."""
    if header:
        parsed = _parse_signature(header, s.entry)
        if parsed:
            return parsed

    asked = 0
    primary: dict[str, Any] | None = None
    for _ in range(max_sig_questions + 1):
        samples = _sig_samples(s, 2)
        if not samples:
            break
        primary, assess, _ = samples[0]
        rivals = [p for _, _, rs in samples for p in rs]
        rivals += [p for p, _, _ in samples[1:] if _sig_differs(primary, p)]  # the samples disagree
        if not rivals:
            return primary
        if asked >= max_sig_questions or not s.can_ask():
            return primary
        if asked >= 1 and not _weak_answer(s.qa[-1][1]):
            return primary  # the user answered informatively; do not ask about the arguments again

        cands: list[str] = []
        for p in [primary] + rivals:
            t = p["text"].rstrip(":")
            if t not in cands:
                cands.append(t)
        q = make_question(s, "signature", assess, {"issue_type": assess["issue_type"], "candidates": cands})
        q = q or _signature_question(s.entry, [primary] + rivals)
        if not s.ask_robust(_open(s.env, q)):
            return primary
        asked += 1

    return primary or {"text": f"def {s.entry}(*args):", "params": [], "kinds": []}

# --------------------------------------------------------------------------- stage 2: formalise + ask

def tool_formalise(s: _Session, sig: dict[str, Any]) -> dict[str, Any]:
    user = s.context() + f"\nFIXED SIGNATURE (do not change): {sig['text']}\n"
    out = _llm_json(s.env, FORMAL_SYSTEM, user)
    formal = _clean_spec(out)
    formal["sig"] = sig  # locked
    formal["rule"] = out.get("rule") if isinstance(out.get("rule"), str) else ""
    formal["readings"] = out.get("readings") if isinstance(out.get("readings"), dict) else {}
    formal["assessment"] = _assessment(out.get("assessment"))
    unc = out.get("uncertainties")
    formal["uncertainties"] = [u for u in unc if isinstance(u, dict)] if isinstance(unc, list) else []
    return formal


_CAT_ORDER = {"output": 0, "semantics": 1, "constant": 2, "edge": 3}


def pick_uncertainty(formal: dict[str, Any], strict: bool, asked: list[str]) -> dict[str, Any] | None:
    """Most serious high-impact uncertainty not yet asked about: issue type first, then confidence."""
    threshold = 0.55 if strict else 0.85
    cands: list[tuple[int, float, int, dict[str, Any]]] = []
    for u in formal["uncertainties"]:
        cat = str(u.get("category", "")).lower()
        assumed = str(u.get("assumed", ""))
        if cat in {"interface", "signature"} or str(u.get("impact", "")).lower() != "high" or not assumed:
            continue
        c = _conf(u.get("confidence"))
        if c >= threshold or any(_similar(assumed, a) for a in asked):
            continue
        issue = str(u.get("issue_type", "")).lower()
        issue = issue if issue in ISSUES else formal["assessment"]["issue_type"]
        cands.append((_ISSUE_RANK.get(issue, 1), c, _CAT_ORDER.get(cat, 4), {**u, "issue_type": issue}))
    if cands:
        return min(cands, key=lambda t: t[:3])[3]

    rd = formal.get("readings") or {}
    diff = rd.get("difference")
    if rd.get("differ") is True and isinstance(diff, str) and diff.strip() and isinstance(rd.get("classic"), str):
        lit = str(rd.get("literal", ""))
        if not any(_similar(lit, a) for a in asked):
            return {
                "category": "semantics", "issue_type": "ambiguity", "assumed": lit,
                "alternatives": [rd["classic"]], "difference": diff, "witness": None,
            }
    return None

# --------------------------------------------------------------------------- stage 3: implementation

def tool_implement(s: _Session, formal: dict[str, Any], extra: str = "") -> str:
    user = s.context() + f"\nSIGNATURE: {formal['sig']['text']}\n\nSPECIFICATION:\n{_fmt_spec(formal)}\n" + extra
    error, code = "", ""
    for _ in range(3):
        resp = _llm(s.env, IMPL_SYSTEM, user + error)
        code = _extract_code(resp) or resp.strip()
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            error = f"\nYour previous code had a syntax error: {e}. Fix it.\n"
            continue
        if not any(isinstance(n, ast.FunctionDef) and n.name == s.entry for n in tree.body):
            error = f"\nYour previous code did not define `{s.entry}` at module level.\n"
            continue
        return code
    return code


def tool_adherence(s: _Session, formal: dict[str, Any], code: str) -> list[str]:
    """Violations of explicit statements: arity (deterministic) plus an LLM check."""
    violations: list[str] = []
    params = _code_params(code, s.entry)
    if params is not None and formal["sig"]["params"] and params != formal["sig"]["params"]:
        violations.append(f"The function must have exactly the parameters {formal['sig']['params']}, not {params}.")
    user = (
        s.context()
        + f"\nRULE: {formal.get('rule', '')}\nSIGNATURE: {formal['sig']['text']}\n\nCODE:\n```python\n{code}\n```\n"
    )
    v = _llm_json(s.env, CHECK_SYSTEM, user, tries=1).get("violations")
    if isinstance(v, list):
        violations += [str(x) for x in v][:4]
    return violations


# --------------------------------------------------------------------------- stage 4: verification (Nagini only)

_DIFF_HARNESS = r'''
import copy, json, math, signal

HAS = hasattr(signal, "SIGALRM")

class TO(Exception):
    pass

def _alarm(sig, frm):
    raise TO()

def same(a, b):
    try:
        if a == b:
            return True
        if type(a) is type(b) and isinstance(a, (list, tuple)) and len(a) == len(b):
            return all(same(x, y) for x, y in zip(a, b))
        if isinstance(a, float) or isinstance(b, float):
            return math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-9)
    except Exception:
        pass
    return False

def load(code):
    try:
        ns = {"__name__": "cand"}
        exec(code, ns)
        return ns[ENTRY]
    except BaseException:
        return None

FNS = [load(A), load(B)]
if HAS:
    signal.signal(signal.SIGALRM, _alarm)
rows = []
for i, args in enumerate(INPUTS):
    vals = []
    for fn in FNS:
        if fn is None:
            vals.append((False, "raises LoadError"))
            continue
        if HAS:
            signal.alarm(2)
        try:
            vals.append((True, fn(*copy.deepcopy(args))))
        except TO:
            vals.append((False, "raises Timeout"))
        except Exception as e:
            vals.append((False, "raises " + type(e).__name__))
        finally:
            if HAS:
                signal.alarm(0)
    (oa, va), (ob, vb) = vals
    if oa and ob:
        differ = not same(va, vb)
    else:
        differ = oa != ob  # both failing is not a difference; one failing is
    rows.append({"i": i, "differ": differ,
                 "a": repr(va)[:200] if oa else va, "b": repr(vb)[:200] if ob else vb})
print("DIFF:" + json.dumps(rows))
'''


def _run_script(env: ClarificationEnvironment, script: str, timeout: int = 40) -> str:
    """Prefer the environment's sandbox. Fall back to a local subprocess (no SIGALRM on Windows; the timeout covers it)."""
    fn = getattr(env, "exec_code", None)
    if callable(fn):
        try:
            return str(fn(script))
        except Exception:
            pass
    try:
        return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=timeout).stdout
    except (subprocess.TimeoutExpired, OSError):
        return ""


def tool_candidate(s: _Session, sig: dict[str, Any]) -> str:
    """Independent first version: only the task, the signature and the clarifications so far. Saved for step 4b."""
    bare = {"sig": sig, "rule": "", "requires": [], "ensures": [], "examples": []}
    return tool_implement(s, bare, "\nWrite the standard textbook version of this exercise, from the task alone.\n")


def tool_probe_inputs(s: _Session, sig: dict[str, Any]) -> list[list[Any]]:
    out = _llm_json(s.env, PROBE_SYSTEM, s.context() + f"\nSIGNATURE: {sig['text']}\n")
    arity, seen, res = len(sig["params"]), set(), []
    for x in out.get("inputs") or []:
        try:
            v = _literal(x)
        except (ValueError, SyntaxError):
            continue
        if not isinstance(v, (list, tuple)) or (arity and len(v) != arity) or repr(v) in seen:
            continue
        seen.add(repr(v))
        res.append(list(v))
    return res[:12]


def tool_diff(s: _Session, sig: dict[str, Any], cand: str, code: str) -> dict[str, Any] | None:
    """Smallest input on which the two implementations disagree, or None."""
    inputs = tool_probe_inputs(s, sig)
    if not inputs:
        return None
    head = f"A = {cand!r}\nB = {code!r}\nENTRY = {s.entry!r}\nINPUTS = {inputs!r}\n"
    for line in reversed(_run_script(s.env, head + _DIFF_HARNESS).splitlines()):
        if not line.startswith("DIFF:"):
            continue
        try:
            rows = json.loads(line[len("DIFF:") :])
        except json.JSONDecodeError:
            return None
        bad = [r for r in rows if r.get("differ") and isinstance(r.get("i"), int) and r["i"] < len(inputs)]
        if not bad:
            return None
        r = min(bad, key=lambda r: len(repr(inputs[r["i"]])))
        return {"args": inputs[r["i"]], "a": r["a"], "b": r["b"], "n_diff": len(bad), "n": len(rows)}
    return None


def tool_judge_diff(s: _Session, sig: dict[str, Any], cand: str, code: str, diff: dict[str, Any]) -> dict[str, Any]:
    call = f"{s.entry}({', '.join(repr(a) for a in diff['args'])})"
    user = (
        s.context()
        + f"\nSIGNATURE: {sig['text']}\n\nIMPLEMENTATION A:\n```python\n{cand}\n```\n"
        + f"\nIMPLEMENTATION B:\n```python\n{code}\n```\n"
        + f"\nCALL: {call}\nRESULT OF A: {diff['a']}\nRESULT OF B: {diff['b']}\n"
        + f"(They disagree on {diff['n_diff']} of {diff['n']} compared inputs.)\n"
    )
    return _llm_json(s.env, JUDGE_DIFF_SYSTEM, user, tries=1)


def tool_resolve_differences(
    s: _Session, sig: dict[str, Any], formal: dict[str, Any], cand: str, code: str, max_diff_questions: int
) -> tuple[str, dict[str, Any]]:
    """Compare the saved candidate with the final code. Ask when the clarifications do not settle a difference."""
    for attempt in range(max_diff_questions + 1):
        diff = tool_diff(s, sig, cand, code)
        if not diff:
            break
        verdict = tool_judge_diff(s, sig, cand, code, diff)
        if verdict.get("settled") is True:
            if verdict.get("right") == "A":  # the clarifications back the candidate: correct the final code once
                call = f"{s.entry}({', '.join(repr(a) for a in diff['args'])})"
                code = tool_implement(
                    s, formal,
                    f"\nFor the call {call} the correct result is {diff['a']}, not {diff['b']}.\nPREVIOUS CODE:\n{code}\n",
                )
            break
        q = verdict.get("question")
        if attempt >= max_diff_questions or not s.can_ask() or not isinstance(q, str) or "?" not in q:
            break
        if not s.ask_robust(_open(s.env, _one_question(q))):
            break
        formal = tool_formalise(s, sig)
        code = tool_implement(s, formal)
    return code, formal

_NAGINI_HEADER = "from nagini_contracts.contracts import *\nfrom typing import List, Dict, Set, Tuple, Optional\n\n"


def _inject_spec(code: str, entry: str, formal: dict[str, Any]) -> str:
    code = textwrap.dedent(code).strip("\n")
    fn = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef) and n.name == entry)
    first = fn.body[0]
    has_doc = isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str)
    if first.lineno == fn.lineno:
        raise ValueError("function body must start on its own line")
    insert_at = (fn.body[1].lineno - 1) if has_doc and len(fn.body) > 1 else (first.end_lineno if has_doc else first.lineno - 1)
    indent = " " * first.col_offset
    spec_lines = [indent + f"Requires({r})" for r in formal["requires"]] + [indent + f"Ensures({e})" for e in formal["ensures"]]
    lines = code.splitlines()
    return "\n".join(lines[:insert_at] + spec_lines + lines[insert_at:]) + "\n"


def tool_nagini(code: str, entry: str, formal: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
    """Works only if `nagini` is on the PATH of the machine running the algorithm."""
    exe = shutil.which("nagini")
    if not exe:
        return {"status": "unavailable"}
    try:
        program = _NAGINI_HEADER + _inject_spec(code, entry, formal)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "to_verify.py"
            path.write_text(program)
            cmd = [exe, str(path), "--float-encoding", "real"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout + proc.stderr)[-2000:]
    except (ValueError, SyntaxError, subprocess.TimeoutExpired, OSError) as e:
        return {"status": "inconclusive", "output": str(e)}
    if proc.returncode == 0 and "Verification successful" in out:
        return {"status": "verified", "output": out}
    if re.search(r"not supported|unsupported|type error|invalid program|could not|unrecognized arguments|usage:", out, re.I):
        return {"status": "inconclusive", "output": out}
    if re.search(r"nagini_translation|AttributeError|NoneType|KeyError|IndexError|AssertionError|RecursionError", out):
        return {"status": "inconclusive", "output": out}
    return {"status": "failed", "output": out}


def tool_verify(code: str, entry: str, formal: dict[str, Any], use_nagini: bool) -> dict[str, Any]:
    """Only a 'failed' status counts as a failure (verified, failed, inconclusive, unavailable, skipped)."""
    if not use_nagini or not (formal["requires"] or formal["ensures"]):
        return {"ok": True, "status": "skipped", "failures": []}
    nag = tool_nagini(code, entry, formal)
    failures = [{"kind": "nagini", "detail": nag["output"]}] if nag["status"] == "failed" else []
    return {"ok": nag["status"] != "failed", "status": nag["status"], "failures": failures}


def _score(report: dict[str, Any]) -> int:
    return len(report["failures"])


def tool_diagnose(s: _Session, formal: dict[str, Any], code: str, failures: list[dict[str, Any]]) -> tuple[dict[str, Any], str | None]:
    user = (
        s.context()
        + f"\nSIGNATURE (fixed): {formal['sig']['text']}\n\nSPECIFICATION:\n{_fmt_spec(formal)}\n\nCANDIDATE:\n```python\n{code}\n```\n"
        + f"\nFAILURES:\n{json.dumps(failures[:5], indent=1)}\n"
        + f"\nASKING THE USER IS {'ALLOWED' if s.can_ask() else 'NOT ALLOWED'}.\n"
    )
    resp = _llm(s.env, DIAG_SYSTEM, user)
    return (_extract_json(resp) or {}), _extract_code(resp)


# --------------------------------------------------------------------------- algorithm

class SpecGuidedClarification(ClarificationAlgorithmBase):
    def run(self, env: ClarificationEnvironment, problem: dict[str, Any]) -> str:
        max_q = int(self.config.get("max_questions", 7))
        max_sig_q = int(self.config.get("max_signature_questions", 2))
        max_repairs = int(self.config.get("max_repairs", 2))
        use_gate = bool(self.config.get("use_quality_gate", False))
        use_nagini = bool(self.config.get("use_nagini", False))
        use_diff = bool(self.config.get("use_diff", False))
        max_diff_q = int(self.config.get("max_diff_questions", 1))
        evolve_task_description = self.config.get("evolve_description", True)

        s = _Session(env, problem, max_q, evolve=bool(evolve_task_description))
        header = _header_from_prompt(s.prompt, s.entry)
        strict = _looks_specified(s.prompt)

        # 1) signature first; ask an open question on serious doubt
        sig = tool_extract_signature(s, header, max_sig_q)

        # 1b) save an independent first implementation (task + signature + clarifications so far)
        candidate = tool_candidate(s, sig) if use_diff else None

        # 2) formalise; the judge verdict decides whether to ask, the issue type decides how
        formal = tool_formalise(s, sig)
        asked: list[str] = []
        while s.can_ask():
            if use_gate and formal["assessment"]["verdict"] == "correct":
                break
            u = pick_uncertainty(formal, strict, asked)
            if not u:
                break
            q = make_question(s, str(u.get("category", "")), formal["assessment"], u)
            if not q or not s.ask_robust(_open(env, q)):
                break
            asked.append(str(u.get("assumed", "")))
            formal = tool_formalise(s, sig)

        # 3) implement and check adherence to explicit statements
        code = tool_implement(s, formal)
        for _ in range(2):
            violations = tool_adherence(s, formal, code)
            if not violations:
                break
            code = tool_implement(
                s, formal, "\nFIX THESE PROBLEMS IN YOUR PREVIOUS ATTEMPT:\n- " + "\n- ".join(violations) + f"\nPREVIOUS CODE:\n{code}\n"
            )

        # 3b) compare the final code with the saved candidate; ask when the difference is not settled
        if candidate:
            code, formal = tool_resolve_differences(s, sig, formal, candidate, code, max_diff_q)

        # 4) verify with Nagini (unchanged)
        report = tool_verify(code, s.entry, formal, use_nagini)
        best = (_score(report), code)

        for _ in range(max_repairs):
            if report["ok"]:
                break
            out, new_code = tool_diagnose(s, formal, code, report["failures"])
            verdict, q = out.get("verdict"), out.get("question")

            if verdict == "unclear" and isinstance(q, str) and s.ask_robust(_open(env, q)):
                formal = tool_formalise(s, sig)
                code = tool_implement(s, formal)
            elif verdict == "spec_bug":
                new = _clean_spec(out)
                formal = {**formal, "requires": new["requires"], "ensures": new["ensures"]}
            elif new_code:
                code = new_code
            else:
                code = tool_implement(s, formal, f"\nYOUR PREVIOUS CODE FAILED:\n{json.dumps(report['failures'][:4])}\nPREVIOUS CODE:\n{code}\n")

            report = tool_verify(code, s.entry, formal, use_nagini)
            if _score(report) < best[0]:
                best = (_score(report), code)

        return best[1]