# SPDX-FileCopyrightText: 2026 Your Name <you@example.org>
#
# SPDX-License-Identifier: MIT

"""SpecGuidedClarification (v4).

First fixes the function signature (number and types of parameters), asking the human when the
description leaves it in serious doubt. The clarified task is then formalised as a rule, a Nagini-style
contract and a ledger of uncertainties; the most critical uncertain decision is asked as one atomic
question. The implementation is checked against clarifications (adherence), executable contracts and
authoritative examples (run in env.exec_code; Nagini too if installed).

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

Background: the description is often a short, deliberately blurred version of a classic programming exercise.
The number and types of the parameters may not be stated. Wrong arity is fatal: a test calls the function with
fixed positional arguments. Think about which arguments a typical call of this function would pass.

Reply with one ```json block:
{"signature": "def f(a: List[int], b: int) -> bool:",
 "confidence": 0.0,
 "reasoning": "one or two sentences: which arguments, why",
 "alternatives": ["def f(a: List[int]) -> bool:", "..."],
 "question": "..."}

Rules:
- Fully annotate all parameters and the return type with typing names. Keep the given entry_point name.
- Minimal signature: a parameter exists only if the description or the clarifications indicate it. A value that
  is not described as variable (a threshold, a cut-off, a count) is a hard-coded constant, not a parameter,
  UNLESS the task would be meaningless or very unusual without it.
- Items under USER CLARIFICATIONS are settled and override everything. Never ask about them again.
- confidence = probability that your signature has exactly the number of parameters and the parameter types that
  a typical test of this function uses. Use 0.7 or less if the description leaves open whether a quantity (a count,
  a threshold, a second operand, an index) is passed in or fixed, whether the input is one collection or several
  arguments, or how nested the input is (flat list, list of tuples, matrix...).
- alternatives: other plausible signatures (empty list if there is none).
- question: ONE sentence, exactly one question mark, asking only about the arguments of the function (how many
  and what kind). Objective; do not mention tests; do not presuppose a parameter that nobody stated; name the
  competing readings, e.g. "Does `f` take only a list of numbers, or also a second integer giving how many items
  to return?". Use null if confidence is above 0.9."""

FORMAL_SYSTEM = """You are a requirements analyst. Turn a task description (plus any user clarifications) into a
precise specification, and list what is still uncertain.

Background: the description is often a short, deliberately blurred version of a classic programming exercise.
Details such as the exact criterion or formula, constants (thresholds, cut-offs), the form of the return value,
or the exact handling of edge cases may have been removed. The simplest reading is NOT automatically the
intended one. The function name and wording are evidence (for example "recursive" suggests nested data,
"Occ" suggests occurrences), but they can mislead.

The SIGNATURE is FIXED and already settled. Do not change, question or list uncertainties about it.

Reply with one ```json block:
{"rule": "1-3 sentences: exactly what the function computes, from which inputs, and what it returns",
 "requires": ["expr"], "ensures": ["expr"],
 "examples": [{"args": "[a1, b1]", "expected": "value"}],
 "uncertainties": [{"category": "semantics|constant|output|edge",
                    "assumed": "what you assumed", "alternatives": ["...", "..."],
                    "confidence": 0.0, "impact": "high|low", "question": "..."}]}

Rules:
- Items under USER CLARIFICATIONS are settled and override everything. Never list them as uncertain. If an
  answer says the user cannot say more, pick the standard reading and give it confidence 1.0.
- requires/ensures: single Python expressions in Nagini style: Result(), Old(x), Implies(a, b); len, sum, min, max,
  sorted, set, all, any, abs, isinstance are allowed. State only what the description or clarifications establish.
  A missing clause is better than a guessed one. Describe properties; do not re-implement.
- examples: ONLY input/output pairs literally given in the description or derivable with certainty from the
  clarifications. Never compute your own. Use [] if there are none.
- uncertainties: each decision where a competent developer could choose differently and an ordinary unit test
  would notice. confidence = probability that your assumption matches what a typical test-suite for this function
  expects. Use 0.6 or less whenever the description names no criterion, formula or constant for something the
  function must decide. Order by importance: semantics, constant, output, edge.
- Do NOT list: the signature, int versus float, mutating versus returning, naming, performance, style,
  invalid-type handling.
- question: ONE sentence with exactly one question mark, asking for ONE missing fact. Objective, not guessable, no
  mention of tests or implementation techniques, and it must not presuppose details nobody stated. If the
  alternatives are unknown, ask openly, for example "What condition must a substring satisfy to be counted?"."""

IMPL_SYSTEM = """You implement a Python function from a task description, a rule, a signature, a contract and user
clarifications. Reply with exactly one ```python block with the complete code (imports included, standard library
only). Rules:
- Exactly the given function name and parameters. Never add, remove or rename parameters. If a constant is not
  specified, hard-code the most standard value.
- User clarifications override everything else. Do not add behaviour nobody asked for.
- No printing, no input(). Do not mutate the arguments.
- Be efficient for large inputs: no loop proportional to the input VALUE, use closed forms, logarithmic bounds or
  early termination. Avoid deep recursion on long inputs.
- Mind edge cases of built-ins (negative numbers, empty inputs, nested data) and implement the rule as stated."""

CHECK_SYSTEM = """Check code against the requirements. List violations of EXPLICIT statements in the description, the
clarifications or the rule: wrong number, order or type of parameters, extra parameters that nobody asked for,
wrong return form, ignored clarifications. Do not flag style or unverifiable guesses.
Reply with one ```json block: {"violations": ["..."]} (empty list if none)."""

DIAG_SYSTEM = """Nagini could not verify a candidate implementation against its specification. Decide who is wrong.
The Nagini output gives the violated clause and a source line. Line numbers refer to a program in which the
Requires/Ensures lines were inserted at the top of the function body. The specification was written by a model and
may itself be wrong or too strong. Reason about the rule step by step before deciding.
The signature is fixed and must not change.
"""

ATOMIC_SYSTEM = """Rewrite the text as ONE atomic, objective question (one sentence, exactly one question mark) that asks
for the single most important missing fact. Do not offer several topics. Do not mention tests. Reply with the
question only."""


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


def _clean_spec(out: dict[str, Any], old: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keep only valid, non-degenerate clauses and literal inputs/examples."""
    req = [r for r in out.get("requires") or [] if _valid_expr(r) and r.strip() != "False"]
    ens = [e for e in out.get("ensures") or [] if _valid_expr(e) and e.strip() != "True"]
    examples = (old or {}).get("examples", [])
    if "examples" in out:
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
    return {"text": sig, "params": [a.arg for a in fn.args.args]}


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

    def context(self) -> str:
        s = f"TASK DESCRIPTION:\n{self.prompt}\n\nENTRY POINT: {self.entry}\n"
        if self.qa:
            s += "\nUSER CLARIFICATIONS (authoritative):\n" + "\n".join(f"Q: {q}\nA: {a}" for q, a in self.qa) + "\n"
        return s


def _atomic(env: ClarificationEnvironment, q: str) -> str:
    q = " ".join(q.split())
    compound = q.count("?") > 1 or len(q) > 240 or re.search(r"\b(and|or)\s+(what|how|which|should|does|is|do|are)\b", q, re.I)
    if not compound:
        return q
    out = " ".join(_llm(env, ATOMIC_SYSTEM, q).strip().strip("`").split())
    if "?" in out:
        out = out[: out.index("?") + 1]
        if len(out) >= 10:
            return out
    return q.split("?")[0].strip() + "?"


# --------------------------------------------------------------------------- stage 1: signature

def tool_extract_signature(s: _Session, header: str | None, strict: bool, max_sig_questions: int) -> dict[str, Any]:
    """Determine number and types of the parameters; ask only on serious doubt."""
    if header:
        parsed = _parse_signature(header, s.entry)
        if parsed:
            return parsed

    threshold = 0.6 if strict else 0.75
    asked = 0
    primary: dict[str, Any] | None = None

    for _ in range(max_sig_questions + 1):
        samples: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for _k in range(2):  # two independent proposals: disagreement on arity signals real doubt
            out = _llm_json(s.env, SIGNATURE_SYSTEM, s.context(), tries=1)
            parsed = _parse_signature(out.get("signature"), s.entry)
            if parsed:
                samples.append((out, parsed))
        if not samples:
            break
        primary = samples[0][1]

        arity_differs = len(samples) == 2 and len(samples[0][1]["params"]) != len(samples[1][1]["params"])
        conf = min(_conf(o.get("confidence")) for o, _ in samples)
        if not (arity_differs or conf < threshold):
            return primary
        if asked >= max_sig_questions or not s.can_ask():
            return primary

        q = next(
            (o["question"] for o, _ in samples if isinstance(o.get("question"), str) and len(o["question"].strip()) >= 10),
            None,
        )
        if not q and arity_differs:
            a, b = samples[0][1], samples[1][1]
            q = f"Does `{s.entry}` take the arguments ({', '.join(a['params'])}) or ({', '.join(b['params'])})?"
        if not q or any(_similar(q, prev) for prev, _ in s.qa):
            return primary
        if not s.ask(_atomic(s.env, q)):
            return primary
        asked += 1

    return primary or {"text": f"def {s.entry}(*args):", "params": []}


# --------------------------------------------------------------------------- stage 2: formalise + ask

def tool_formalise(s: _Session, sig: dict[str, Any]) -> dict[str, Any]:
    user = s.context() + f"\nFIXED SIGNATURE (do not change): {sig['text']}\n"
    out = _llm_json(s.env, FORMAL_SYSTEM, user)
    formal = _clean_spec(out)
    formal["sig"] = sig  # the signature is locked
    formal["rule"] = out.get("rule") if isinstance(out.get("rule"), str) else ""
    unc = out.get("uncertainties")
    formal["uncertainties"] = [u for u in unc if isinstance(u, dict)] if isinstance(unc, list) else []
    return formal


_CAT_ORDER = {"semantics": 0, "constant": 1, "output": 2, "edge": 3}


def pick_question(unc: list[dict[str, Any]], strict: bool, asked: list[str]) -> str | None:
    """Most critical uncertain, high-impact, not-yet-asked decision."""
    threshold = 0.5 if strict else 0.8
    cands: list[tuple[int, float, str]] = []
    for u in unc:
        q = u.get("question")
        if not isinstance(q, str) or len(q.strip()) < 10:
            continue
        cat = str(u.get("category", "")).lower()
        if cat == "interface":  # settled in the signature stage
            continue
        if str(u.get("impact", "")).lower() != "high":
            continue
        c = _conf(u.get("confidence"))
        if c >= threshold:
            continue
        if any(_similar(q, a) for a in asked):
            continue
        cands.append((_CAT_ORDER.get(cat, 4), c, q.strip()))
    return min(cands)[2] if cands else None


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


# --------------------------------------------------------------------------- stage 4: verification

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
    """Optional. Works only if `nagini` is on the PATH of the machine running the algorithm."""
    exe = shutil.which("nagini")
    if not exe:
        return {"status": "unavailable"}
    try:
        program = _NAGINI_HEADER + _inject_spec(code, entry, formal)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "to_verify.py"
            path.write_text(program)
            cmd = [exe, "--float-encoding", "real", str(path)]
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
    """Nagini is the only verifier. Only a 'failed' status counts as a failure.

    status is one of: verified, failed, inconclusive, unavailable, skipped.
    """
    if not use_nagini or not (formal["requires"] or formal["ensures"]):
        return {"ok": True, "status": "skipped", "failures": []}
    nag = tool_nagini(code, entry, formal)
    status = nag["status"]
    failures = [{"kind": "nagini", "detail": nag["output"]}] if status == "failed" else []
    return {"ok": status != "failed", "status": status, "failures": failures}


def _score(report: dict[str, Any]) -> int:
    return len(report["failures"])

# --------------------------------------------------------------------------- stage 5: diagnosis

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

        # 1) fix the signature first (number and types of parameters); ask only on serious doubt
        sig = tool_extract_signature(s, header, strict, max_sig_q)

        # 2) formalise; ask about the most critical remaining uncertainty; re-formalise with the answer
        formal = tool_formalise(s, sig)
        while s.can_ask():
            q = pick_question(formal["uncertainties"], strict, [q for q, _ in s.qa])
            if not q or not s.ask(_atomic(env, q)):
                break
            formal = tool_formalise(s, sig)

        # 3) implement and check adherence to explicit statements (signature, clarifications)
        code = tool_implement(s, formal)
        for _ in range(2):
            violations = tool_adherence(s, formal, code)
            if not violations:
                break
            code = tool_implement(
                s, formal, "\nFIX THESE PROBLEMS IN YOUR PREVIOUS ATTEMPT:\n- " + "\n- ".join(violations) + f"\nPREVIOUS CODE:\n{code}\n"
            )

        # 4) verify with Nagini, diagnose and repair against its output
        report = tool_verify(code, s.entry, formal, use_nagini)
        best = (_score(report), code)

        for _ in range(max_repairs):
            if report["ok"]:
                break
            out, new_code = tool_diagnose(s, formal, code, report["failures"])
            verdict, q = out.get("verdict"), out.get("question")

            if verdict == "unclear" and isinstance(q, str) and s.ask(_atomic(env, q)):
                formal = tool_formalise(s, sig)
                code = tool_implement(s, formal)
            elif verdict == "spec_bug":
                formal = {**formal, **_clean_spec(out, formal), "examples": formal["examples"]}
            elif new_code:
                code = new_code
            else:
                code = tool_implement(s, formal, f"\nYOUR PREVIOUS CODE FAILED:\n{json.dumps(report['failures'][:4])}\nPREVIOUS CODE:\n{code}\n")

            report = tool_verify(code, s.entry, formal, use_nagini)
            if _score(report) < best[0]:
                best = (_score(report), code)

        return best[1]