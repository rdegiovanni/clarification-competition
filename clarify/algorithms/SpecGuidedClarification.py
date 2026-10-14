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

SIGNATURE_SYSTEM = """You determine the exact Python signature of the function `entry_point` from a task description.

Background: descriptions are short, deliberately blurred versions of classic exercises. A hidden test-suite calls
the function with fixed positional arguments. A wrong number of arguments, or a wrong kind of argument (one list
versus two lists, a list versus a single number, a flat list versus a list of pairs), fails every test.

Work like the author of the test-suite:
1. Write three different plausible test calls, as in `assert f(<args>) == <expected>`. Give only the argument
   lists, as Python literals. Different authors may have chosen different shapes: let the three calls reflect the
   plausible range, not one favourite.
2. From the calls and the description, choose the most probable signature.

Reply with one ```json block:
{"calls": ["[arg1, arg2]", "[arg1, arg2]", "[arg1, arg2]"],
 "signature": "def f(a: List[int], b: int) -> bool:",
 "confidence": 0.0,
 "alternatives": ["def f(...) -> ...:"]}

Rules:
- Fully annotate with typing names (List, Dict, Tuple, Optional...). Keep the given entry_point name.
- Read every noun in the description and in the function name as evidence about the inputs: "between X" or a plural
  such as "lists" means separate operands; "pairs" or "tuples" means a collection of tuples; a geometric solid needs
  all the dimensions its volume needs; "matrix" means a list of lists; "recursive" or "nested" means nested data;
  "word", "text" or "string" means a string.
- Do not minimise and do not maximise the number of parameters: choose what the description implies. A fixed
  threshold stays a constant only if the description gives no sign that the caller supplies it.
- USER CLARIFICATIONS settle everything they cover. If an answer rejects a proposed shape (says No to it), your
  signature MUST differ from it. Answers marked partial or evasive must not be relied on.
- confidence = probability that the number of parameters and their kinds match what the test-suite passes. Use
  0.7 or less whenever the description does not state the inputs explicitly.
- alternatives: other plausible signatures with a different number or kind of parameters ([] if none)."""

FORMAL_SYSTEM = """You are a requirements analyst. Turn a task description (plus any user clarifications) into a
precise specification, and list what is still uncertain.

Background: the description is a short, deliberately blurred version of a classic programming exercise. The exact
criterion or formula, constants, which items are affected, the form of the return value or the counting rule may
have been removed. The simplest reading is NOT automatically the intended one.

The SIGNATURE is FIXED and settled. Do not change it, question it or list uncertainties about it.

Reply with one ```json block:
{"readings": {"literal": "what the description says, read word by word",
              "classic": "the standard version of this exercise as you remember it (inputs, output, exact criterion), or null",
              "differ": true, "difference": "what differs between them, or null"},
 "rule": "1-3 sentences: exactly what the function computes and returns",
 "requires": ["expr"], "ensures": ["expr"],
 "examples": [{"args": "[a1, b1]", "expected": "value"}],
 "uncertainties": [{"category": "output|semantics|constant|edge",
                    "assumed": "...", "alternatives": ["...", "..."],
                    "witness": "an input on which the alternatives give different results, or null",
                    "confidence": 0.0, "impact": "high|low", "question": "..."}]}

Rules:
- Account for every content word of the function name and of the description. A word that your rule does not use
  (for example a qualifier such as "lowercase", "dirty", "special", "long", or a name part such as "Occ") is an
  uncertainty.
- Compare the verb of the description with the prefix of the name. is_/check/test suggest a boolean, find/get/
  compute/count suggest a value. If they disagree, the OUTPUT form is uncertain.
- readings.differ is true if the classic version would give a different result from the literal reading on an input
  that an ordinary test would try (which occurrences are affected, which criterion, which output form, which
  counting rule). If differ is true, include a matching uncertainty with confidence 0.5 or less.
- rule: follow the clarifications; where nothing settles a point, follow the literal reading.
- USER CLARIFICATIONS are settled and override everything. Never list them as uncertain. Partial or evasive answers
  are NOT settled. If an answer says the user cannot say more, take the standard reading with confidence 1.0.
- requires/ensures: single Python expressions in Nagini style: Result(), Old(x), Implies(a, b); len, sum, min, max,
  sorted, set, all, any, abs, isinstance are allowed. State only what the description or clarifications establish.
  A missing clause is better than a guessed one. Describe properties; do not re-implement.
- examples: ONLY input/output pairs literally given in the description or derivable with certainty from the
  clarifications. Never compute your own. Use [] if there are none.
- uncertainties: each decision where a competent developer could choose differently and an ordinary unit test would
  notice. confidence = probability that your assumption matches what the test-suite expects. Use 0.6 or less
  whenever the description names no criterion, formula or constant for something the function must decide.
  Order by importance: output, semantics, constant, edge.
- Do NOT list: the signature, int versus float, mutating versus returning, naming, performance, style, invalid input.
- question: ONE sentence with exactly one question mark, in OPEN form, beginning with What, Which or How. It asks
  the user to state the missing fact, for example "What condition must a substring satisfy to be counted?", "What
  should the function return?" or "Which occurrences of the character are removed?". Never propose a default reading
  inside the question, never ask yes/no, and do not mention tests or implementation techniques."""

IMPL_SYSTEM = """You implement a Python function from a task description, a rule, a signature, a contract and user
clarifications. Reply with exactly one ```python block with the complete code (imports included, standard library
only). Rules:
- Exactly the given function name and parameters. Never add, remove or rename parameters. If a constant is not
  specified, hard-code the most standard value.
- User clarifications override everything else. Do not add behaviour nobody asked for. No assert statements and no
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
wrong return form, ignored clarifications. Do not flag style or unverifiable guesses.
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


# --------------------------------------------------------------------------- helpers

def _extract_json(text: str) -> dict[str, Any] | None:
    m = re.search(r"```json\s*(\{.*\})\s*```", text, re.S)
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


def _clean_spec(out: dict[str, Any]) -> dict[str, Any]:
    """Keep only valid, non-degenerate clauses and literal examples."""
    req = [r for r in out.get("requires") or [] if _valid_expr(r) and r.strip() != "False"]
    ens = [e for e in out.get("ensures") or [] if _valid_expr(e) and e.strip() != "True"]
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


def _fmt_spec(f: dict[str, Any]) -> str:
    lines = [f"Rule: {f['rule']}"] if f.get("rule") else []
    lines += [f"Requires({r})" for r in f["requires"]] + [f"Ensures({e})" for e in f["ensures"]]
    lines += [f"Example: f(*{a!r}) == {e!r}" for a, e in f["examples"]]
    return "\n".join(lines) or "(no contract)"


class _Session:
    """Per-problem state: task text, question budget and Q/A pairs."""

    def __init__(self, env: ClarificationEnvironment, problem: dict[str, Any], max_questions: int):
        self.env = env
        self.prompt: str = problem["prompt"]
        self.entry: str = problem["entry_point"]
        self.max_q = max_questions
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
        return True

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
        s = f"TASK DESCRIPTION:\n{self.prompt}\n\nENTRY POINT: {self.entry}\n"
        if self.qa:
            lines = []
            for q, a in self.qa:
                flag = "  (partial or evasive answer: do not rely on it)" if _weak_answer(a) else ""
                lines.append(f"Q: {q}\nA: {a}{flag}")
            s += "\nUSER CLARIFICATIONS (authoritative):\n" + "\n".join(lines) + "\n"
        return s


_YES_NO_START = re.compile(r"^\s*(should|does|do|is|are|can|will|would|has|have|did)\b", re.I)


def _open(env: ClarificationEnvironment, q: str) -> str:
    """Questions must be open (What/Which/How) and single: yes/no and compound ones are rewritten."""
    q = " ".join(q.split())
    compound = q.count("?") > 1 or len(q) > 240
    if not _YES_NO_START.match(q) and not compound:
        return q
    out = _one_question(_llm(env, OPEN_SYSTEM, q))
    return out if "?" in out and len(out) >= 10 else _one_question(q)


# --------------------------------------------------------------------------- stage 1: signature

def _sig_samples(s: _Session, n: int = 2) -> list[tuple[dict[str, Any], dict[str, Any], set[int], set[int]]]:
    samples = []
    for _ in range(n):
        out = _llm_json(s.env, SIGNATURE_SYSTEM, s.context(), tries=1)
        parsed = _parse_signature(out.get("signature"), s.entry)
        if not parsed:
            continue
        arities = {len(parsed["params"])}
        for c in out.get("calls") or []:
            try:
                v = _literal(c)
                if isinstance(v, (list, tuple)):
                    arities.add(len(v))
            except (ValueError, SyntaxError):
                pass
        alt: set[int] = set()
        if _conf(out.get("confidence")) < 0.9:
            for a in out.get("alternatives") or []:
                pa = _parse_signature(a, s.entry)
                if pa:
                    alt.add(len(pa["params"]))
        samples.append((out, parsed, arities, alt))
    return samples


def _signature_question(entry: str, sigs: list[dict[str, Any]]) -> str:
    texts = []
    for p in sigs:
        t = p["text"].rstrip(":")
        if t not in texts:
            texts.append(t)
    hint = f" (for example `{texts[0]}` or `{texts[1]}`)" if len(texts) > 1 else ""
    return f"What arguments does `{entry}` take{hint}: how many, and what kind of value is each one?"


def tool_extract_signature(s: _Session, header: str | None, strict: bool, max_sig_questions: int) -> dict[str, Any]:
    """Number and kind of parameters; ask an open question only on serious doubt."""
    if header:
        parsed = _parse_signature(header, s.entry)
        if parsed:
            return parsed

    threshold = 0.6 if strict else 0.85
    asked = 0
    primary: dict[str, Any] | None = None

    for _ in range(max_sig_questions + 1):
        samples = _sig_samples(s, 2)
        if not samples:
            break
        primary = samples[0][1]
        sigs = [p for _, p, _, _ in samples]

        arities: set[int] = set()
        for _, _, ar, alt in samples:
            arities |= ar | alt
        kinds_differ = len({tuple(p["kinds"]) for p in sigs}) > 1
        conf = min(_conf(o.get("confidence")) for o, _, _, _ in samples)
        doubt = len(arities) > 1 or kinds_differ or conf < threshold
        if not doubt:
            return primary
        if asked >= max_sig_questions or not s.can_ask():
            return primary
        if asked >= 1 and not _weak_answer(s.qa[-1][1]):
            return primary  # the user answered informatively; do not ask about the arguments again

        if not s.ask_robust(_signature_question(s.entry, sigs)):
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
    unc = out.get("uncertainties")
    formal["uncertainties"] = [u for u in unc if isinstance(u, dict)] if isinstance(unc, list) else []
    return formal


_CAT_ORDER = {"output": 0, "semantics": 1, "constant": 2, "edge": 3}


def pick_question(env: ClarificationEnvironment, formal: dict[str, Any], strict: bool, asked: list[str]) -> str | None:
    """Most uncertain high-impact decision not yet asked about."""
    threshold = 0.55 if strict else 0.85
    cands: list[tuple[float, int, str]] = []
    for u in formal["uncertainties"]:
        q = u.get("question")
        cat = str(u.get("category", "")).lower()
        if not isinstance(q, str) or len(q.strip()) < 10 or cat in {"interface", "signature"}:
            continue
        if str(u.get("impact", "")).lower() != "high":
            continue
        c = _conf(u.get("confidence"))
        if c >= threshold or any(_similar(q, a) for a in asked):
            continue
        cands.append((c, _CAT_ORDER.get(cat, 4), q.strip()))
    if cands:
        return min(cands)[2]

    rd = formal.get("readings") or {}
    diff = rd.get("difference")
    if rd.get("differ") is True and isinstance(diff, str) and diff.strip():
        q = _one_question(_llm(env, OPEN_SYSTEM, f"The standard version of this exercise differs from the literal reading: {diff}"))
        if "?" in q and len(q) >= 10 and not any(_similar(q, a) for a in asked):
            return q
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
        max_q = int(self.config.get("max_questions", 3))
        max_sig_q = int(self.config.get("max_signature_questions", 2))
        max_repairs = int(self.config.get("max_repairs", 2))
        use_nagini = bool(self.config.get("use_nagini", True))

        s = _Session(env, problem, max_q)
        header = _header_from_prompt(s.prompt, s.entry)
        strict = _looks_specified(s.prompt)

        # 1) signature first; ask an open question on serious doubt
        sig = tool_extract_signature(s, header, strict, max_sig_q)

        # 2) formalise; ask open questions about the most uncertain decisions; re-formalise with each answer
        formal = tool_formalise(s, sig)
        while s.can_ask():
            q = pick_question(env, formal, strict, [q for q, _ in s.qa])
            if not q or not s.ask_robust(_open(env, q)):
                break
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

        # 4) verify with Nagini; diagnose and repair against its output
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