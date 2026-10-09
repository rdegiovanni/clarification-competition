# SPDX-FileCopyrightText: 2026 Matias Brizzio <matiasnbrizzio@gmail.com>
#
# SPDX-License-Identifier: MIT

"""LAASeR 3.0.

Gricean clarification driven by goal-conflict witnesses. The task text is read
cooperatively: anything a competent programmer would fill in by convention is
inferred, not asked. One implementation is generated per plausible reading,
all of them are executed (via env.exec_code) on the stated examples and on
probe inputs, and readings that contradict the examples are discarded. A
witness -- an input on which surviving readings disagree -- or an example that
every reading contradicts is the evidence from which the single clarifying
question is formulated. The final solution is then generated fresh from the
answer, so it is not anchored to any earlier interpretation.

Team: LAASeR - LIST
Team Members: Matias Brizzio, Jordi Cabot, Renzo Degiovanni
Main Contact: matiasnbrizzio@gmail.com
"""

from __future__ import annotations

import ast
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from clarify.baselines import ClarificationAlgorithmBase
from clarify.env import ClarificationEnvironment, LimitsExceededException, TooManyQuestionException
from clarify.runtime import _validate_and_parse_evalplus_result

DEFAULT_READING = "The most natural, conventional reading of the task."
MAX_REPR_IN_EVIDENCE = 80
RESULT_MARKER = "@@LAASER_RESULTS@@"

# --------------------------------------------------------------------------- #
# Prompts (placeholders are <<name>> so JSON braces need no escaping).
# --------------------------------------------------------------------------- #
ANALYSE_TEMPLATE = """
Read the coding task below the way a cooperative listener reads an utterance.
The text is what its author *wrote*; the author's tests encode what they *meant*.
Separate two kinds of facts about what the task requires:
- Truth: anything settled by what the text already says, by convention, or by
  the LOGICAL CONSEQUENCE of what is already stated -- even if never spelled
  out explicitly. (If the scene is already established as night, you don't
  ask whether the sun is out -- that follows from what you already know, it
  is not a gap.) Fill all of this in silently; it is never worth a question.
- Intent: a genuine fork where two readings both survive every stated fact,
  every convention and every logical consequence of the text, and still
  produce different outputs on some input the hidden tests could use. Only
  this is worth flagging.

Task (function to implement: `<<entry_point>>`):
<<prompt>>

Treat every explicit statement in the description, every example and the
signature as a separate goal, and look for:
- conflict:  two goals that cannot both hold (e.g. an example contradicts the description);
- gap:       a test-relevant behaviour that remains undetermined even after applying
             every stated fact, standard convention, and their logical consequences --
             not simply something the text doesn't spell out explicitly;
- ambiguity: a phrase with two readings that give different outputs, neither of
             which is ruled out by the rest of the text.
Naming, style and performance never count.

Reply with JSON only, no prose:
{
  "examples": [{"call": "<python expression calling <<entry_point>>>", "expected": "<python literal>"}],
  "readings": ["<one-sentence interpretation>"],
  "probes":   ["<python expression calling <<entry_point>>>"],
  "issue":    "none | conflict | gap | ambiguity",
  "question": "<the single question that decides between the readings, or empty>"
}
Rules: "examples" are copied from the task text only (empty list if there are
none). Give exactly 1 reading if the task is clear, otherwise 2 or 3 that differ
in observable output. Give up to <<max_probes>> probes, all calling
`<<entry_point>>` with the same argument structure: inputs where the readings
would differ, plus edge cases (empty input, ties, negatives, boundaries).
""".strip()

IMPLEMENT_TEMPLATE = """
Please provide a self-contained Python script implementing `<<entry_point>>` that
solves the task below, under this reading of it:
<<reading>>

Task:
<<prompt>>

Fill in anything the task leaves unsaid the way a competent Python programmer
would by convention. Enclose your solution in ```python and ```. The function
must be named exactly `<<entry_point>>`.
""".strip()

QUESTION_TEMPLATE = """
You are about to implement `<<entry_point>>` for the task below and may ask its
author exactly ONE clarifying question.

Task:
<<prompt>>

<<evidence>>

Write the single question whose answer most changes whether an implementation
passes the author's tests. The question must:
- target exactly one behavioural fact (a return type or format, a boundary or
  tie rule, the meaning of a term, which of two conflicting statements holds,
  the form of an argument), answerable in one sentence;
- be about something that cannot be inferred from the text by convention;
- not ask for test cases, example outputs, the algorithm or the implementation;
- not bundle several questions (no lists, no "and also").

Reply with exactly one line:
QUESTION: <your question>
""".strip()

SOLVE_TEMPLATE = """
Please provide a self-contained Python script implementing `<<entry_point>>` that
solves the following problem:

<<prompt>>

The author was asked a clarifying question and answered:
Q: <<question>>
A: <<answer>>

The answer reveals what the author meant. Follow it exactly, even where it
contradicts your first reading of the task or one of its examples.

Enclose your solution in ```python and ```. The function must be named exactly
`<<entry_point>>`.
""".strip()

REPAIR_TEMPLATE = """
That response wasn't usable: either it had no ```python ... ``` block, the code
inside didn't parse, or it didn't define a function named exactly
`<<entry_point>>`. Reply again with only the corrected implementation, enclosed
in ```python and ```, defining `<<entry_point>>`.
""".strip()

FALLBACK_CODE_TEMPLATE = "def <<entry_point>>(*args, **kwargs):\n    raise NotImplementedError\n"

# Self-contained script run inside env.exec_code: loads every candidate in its
# own namespace and evaluates every call on it, under per-step and global time
# limits. Candidate prints are swallowed; results go to stdout after a marker.
RUNNER_TEMPLATE = r"""
import io, json, signal, sys, time
_DATA = json.loads(<<payload>>)
_REAL_STDOUT = sys.stdout
_START = time.time()

def _alarm(*_):
    raise TimeoutError()

signal.signal(signal.SIGALRM, _alarm)

def _guarded(seconds, fn):
    signal.alarm(seconds)
    try:
        return fn()
    finally:
        signal.alarm(0)

_out = []
for _code in _DATA["candidates"]:
    _entry = {"load_error": None, "results": []}
    _ns = {"__name__": "candidate"}
    sys.stdout = io.StringIO()
    try:
        if time.time() - _START > _DATA["deadline"]:
            raise TimeoutError()
        _guarded(2, lambda: exec(_DATA["preamble"] + "\n" + _code, _ns))
    except BaseException as _e:
        _entry["load_error"] = type(_e).__name__
    if _entry["load_error"] is None:
        for _call, _expected in _DATA["calls"]:
            _r = {"value": None, "error": None, "match": None}
            try:
                if time.time() - _START > _DATA["deadline"]:
                    raise TimeoutError()
                _v = _guarded(1, lambda: eval(_call, _ns))
                _r["value"] = repr(_v)
                if _expected is not None:
                    try:
                        _r["match"] = bool(_v == eval(_expected, _ns))
                    except BaseException:
                        _r["match"] = None
            except BaseException as _e:
                _r["error"] = type(_e).__name__
            _entry["results"].append(_r)
    sys.stdout = _REAL_STDOUT
    _out.append(_entry)

sys.stdout = _REAL_STDOUT
print("\n<<marker>>" + json.dumps(_out))
"""

PREAMBLE = (
    "import math, re, string, itertools, functools, collections, heapq, bisect\n"
    "from typing import *\n"
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
@dataclass
class Candidate:
    code: str
    reading: int
    load_error: str | None = None
    results: list[dict[str, Any]] = field(default_factory=list)

    @property
    def runnable(self) -> bool:
        return self.load_error is None and bool(self.results)


@dataclass
class Witness:
    index: int
    call: str
    groups: dict[str, list[Candidate]]  # output repr -> candidates producing it


def _fill(template: str, **kwargs: Any) -> str:
    for key, value in kwargs.items():
        template = template.replace(f"<<{key}>>", str(value))
    return template


def _fence(code: str) -> str:
    return f"```python\n{code.rstrip()}\n```"


def _short(text: str) -> str:
    return text if len(text) <= MAX_REPR_IN_EVIDENCE else text[: MAX_REPR_IN_EVIDENCE - 3] + "..."


def _llm(env: ClarificationEnvironment, messages: Any) -> str | None:
    try:
        return env.llm(messages)
    except LimitsExceededException:
        return None


def _extract_code(response: str | None, entry_point: str) -> str | None:
    if not response:
        return None
    try:
        code = _validate_and_parse_evalplus_result(response)
    except ValueError:
        return None
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    defines_entry = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entry_point
        for node in tree.body
    )
    return code if defines_entry else None


def _solve(
    env: ClarificationEnvironment, content: str, entry_point: str, repairs: int
) -> str | None:
    messages = [{"role": "user", "content": content}]
    for attempt in range(repairs + 1):
        response = _llm(env, messages)
        if response is None:
            return None
        code = _extract_code(response, entry_point)
        if code:
            return code
        if attempt < repairs:
            messages = messages + [
                {"role": "assistant", "content": response},
                {"role": "user", "content": _fill(REPAIR_TEMPLATE, entry_point=entry_point)},
            ]
    return None


def _parse_json(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _is_expr(expr: Any) -> bool:
    if not isinstance(expr, str) or not expr.strip():
        return False
    try:
        ast.parse(expr.strip(), mode="eval")
    except SyntaxError:
        return False
    return True


def _is_call(expr: Any, entry_point: str) -> bool:
    return _is_expr(expr) and f"{entry_point}(" in expr


def _parse_question(reply: str | None) -> str | None:
    if not reply:
        return None
    for line in reply.splitlines():
        line = line.strip().lstrip("`*- ")
        if line.upper().startswith("QUESTION:"):
            question = line.split(":", 1)[1].strip().strip("`*")
            if question:
                return question
    lines = [line.strip() for line in reply.splitlines() if line.strip()]
    if len(lines) == 1 and lines[0].endswith("?"):
        return lines[0]
    return None


def _execute_all(
    env: ClarificationEnvironment,
    candidates: list[Candidate],
    calls: list[tuple[str, str | None]],
    deadline_s: int,
) -> bool:
    """Run every candidate on every call in ONE env.exec_code container."""
    payload = json.dumps(
        {
            "candidates": [c.code for c in candidates],
            "calls": calls,
            "preamble": PREAMBLE,
            "deadline": deadline_s,
        }
    )
    script = _fill(RUNNER_TEMPLATE, payload=repr(payload), marker=RESULT_MARKER)
    try:
        stdout = env.exec_code(script)
    except Exception:  # Docker unavailable or similar: no execution evidence.
        return False
    if RESULT_MARKER not in stdout:
        return False
    try:
        report = json.loads(stdout.rsplit(RESULT_MARKER, 1)[1].strip().splitlines()[0])
    except (json.JSONDecodeError, IndexError):
        return False
    if len(report) != len(candidates):
        return False
    for cand, entry in zip(candidates, report, strict=True):
        cand.load_error = entry.get("load_error")
        cand.results = entry.get("results", [])
    return True


def _passes(result: dict[str, Any]) -> bool:
    return result["error"] is None and result["match"] is not False


# --------------------------------------------------------------------------- #
# Goal-conflict analysis over executed readings
# --------------------------------------------------------------------------- #
def _gricean_filter(cands: list[Candidate], n_examples: int) -> tuple[list[Candidate], int | None]:
    """Keep the readings consistent with the stated examples.

    Returns (survivors, conflicting_example_index). The index is set when every
    runnable reading contradicts some example: a violation of Quality.
    """
    runnable = [c for c in cands if c.runnable]
    if not runnable or n_examples == 0:
        return runnable, None

    passing = [c for c in runnable if all(_passes(r) for r in c.results[:n_examples])]
    if passing:
        return passing, None

    fails: Counter[int] = Counter()
    for c in runnable:
        for i, r in enumerate(c.results[:n_examples]):
            if not _passes(r):
                fails[i] += 1
    return runnable, fails.most_common(1)[0][0]


def _find_witnesses(
    survivors: list[Candidate],
    calls: list[tuple[str, str | None]],
    cross_reading_only: bool,
    top_k: int = 3,
) -> list[Witness]:
    """Every input on which surviving readings disagree, most-even-split first.

    Returns up to `top_k` witnesses so the single clarifying question can be
    formulated from the whole disagreement surface, not one sampled input --
    several witnesses are often different symptoms of the same underlying
    decision, and seeing all of them is what makes one question incisive
    enough to settle every one of them at once.
    """
    scored: list[tuple[float, Witness]] = []
    for i, (call, _) in enumerate(calls):
        groups: dict[str, list[Candidate]] = {}
        for c in survivors:
            if i < len(c.results) and c.results[i]["error"] is None:
                groups.setdefault(c.results[i]["value"], []).append(c)
        if len(groups) < 2:
            continue
        if cross_reading_only and len({c.reading for g in groups.values() for c in g}) < 2:
            continue
        sizes = [len(g) for g in groups.values()]
        n = sum(sizes)
        entropy = -sum(s / n * math.log(s / n) for s in sizes)
        scored.append((entropy, Witness(index=i, call=call, groups=groups)))
    scored.sort(key=lambda pair: -pair[0])
    return [w for _, w in scored[:top_k]]


def _best(cands: list[Candidate], n_examples: int) -> Candidate:
    pool = [c for c in cands if c.runnable] or cands

    def example_score(c: Candidate) -> int:
        return sum(1 for r in c.results[:n_examples] if _passes(r))

    def agreement(c: Candidate) -> int:
        return sum(
            1
            for other in pool
            if other is not c
            for i, r in enumerate(c.results)
            if i < len(other.results)
            and r["error"] is None
            and other.results[i]["error"] is None
            and other.results[i]["value"] == r["value"]
        )

    return max(pool, key=lambda c: (example_score(c), agreement(c)))


def _evidence(
    analysis: dict[str, Any],
    survivors: list[Candidate],
    conflict_example: int | None,
    witnesses: list[Witness],
) -> tuple[str, bool]:
    """Describe what the executed readings revealed. Returns (text, observed)."""
    hint = ""
    if analysis["question"]:
        hint = f"\nA first analysis of the task suggested asking: {analysis['question']}"

    if conflict_example is not None:
        ex = analysis["examples"][conflict_example]
        got = Counter(
            c.results[conflict_example]["value"]
            for c in survivors
            if c.results[conflict_example]["error"] is None
        ).most_common(1)
        text = (
            "Evidence: every reading of the description contradicts the stated example "
            f"`{_short(ex['call'])}` -> `{_short(ex['expected'])}`"
        )
        if got:
            text += f" (the description seems to give `{_short(got[0][0])}`)"
        text += ". Your question should settle which of the two the author intends."
        return text + hint, True

    if witnesses:
        readings = analysis["readings"]
        lines = [
            "Evidence: readings consistent with everything the task states still behave "
            "differently on these inputs:"
        ]
        for witness in witnesses:
            values = sorted(witness.groups, key=lambda v: -len(witness.groups[v]))[:2]
            parts = []
            for label, value in zip("AB", values, strict=False):
                idx = witness.groups[value][0].reading
                reading = (
                    readings[idx]
                    if idx < len(readings) and len(readings) > 1
                    else "an implementation"
                )
                parts.append(f"{label} ({reading}) -> `{_short(value)}`")
            lines.append(f"- `{_short(witness.call)}`: " + "; ".join(parts))
        lines.append(
            "These may be different symptoms of the same underlying decision. Ask the one "
            "question whose answer would settle all of them at once, phrased as a question "
            "about behaviour, not about any one of these particular inputs."
        )
        return "\n".join(lines) + hint, True

    if analysis["issue"] != "none" and analysis["question"]:
        return f"Evidence: a first analysis flagged a possible {analysis['issue']}." + hint, False

    return (
        "Evidence: the plausible readings of the task agree on every input tried. Ask about "
        "the single most critical fact a competent programmer could still get wrong "
        "(for example the exact form of the arguments, the return type or an edge case)." + hint,
        False,
    )


# --------------------------------------------------------------------------- #
# Algorithm
# --------------------------------------------------------------------------- #
class LAASeR3Algorithm(ClarificationAlgorithmBase):
    """Gricean clarification via goal-conflict witnesses.

    Design rationale -- based on the argument of Matias Brizzio's PhD thesis.
    Following Grice ("Utterer's meaning, sentence-meaning, and word-meaning",
    1968), the thesis separates the *sentence meaning* of a specification (the
    literal text a tool can process) from the engineer's *speaker meaning* (the
    intent that text is a lossy projection of), and argues that no algorithm can
    certify an output is what the engineer *meant*, only that it is close to
    what they *wrote*. Here the task prompt is the sentence meaning and the
    hidden tests are the speaker meaning; the clarifying question is the only
    channel through which speaker meaning can enter. The algorithm therefore
    treats that question as a scarce resource to be spent where the text
    demonstrably underdetermines behaviour.

    Cooperative reading (Grice, "Logic and Conversation", 1975). The prompt is
    read as the utterance of a cooperative author: whatever a competent
    programmer would fill in the same way is an implicature, inferred rather
    than asked. Clarification is reserved for observable breakdowns of the
    maxims:
      * Quality  -- every reading of the description contradicts a stated
                    example (inconsistency);
      * Quantity -- the goals leave an output undetermined (incompleteness);
      * Manner   -- a phrase admits readings with different outputs
                    (ambiguity).

    Goal-conflict analysis (Degiovanni et al.; Brizzio et al.). Each statement,
    example and the signature is a goal. Analogous to a boundary condition, a
    *witness* is a concrete input on which readings that satisfy all stated
    goals diverge. Witnesses are found by executing one implementation per
    reading through `env.exec_code`; readings that contradict the examples are
    discarded first, since the examples are part of the utterance. The question
    is then formulated from the most informative witness, so it targets one
    test-relevant fact (Quantity, Relation) in behavioural terms (Manner),
    without asking for test cases.

    Asking policy. With `ask_policy="always"` the single turn is always spent,
    because TDS discounts one turn only to 1/log10(11) ~ 0.96 while a wrong
    guess loses the whole task; the evidence then decides *what* is asked. With
    `ask_policy="evidence"` a question is asked only when a maxim is
    observably violated, the strict Gricean reading.

    After the answer, the solution is generated fresh from the prompt plus the
    Q/A pair, so it is not anchored to any pre-clarification reading.
    """

    DEFAULT_CONFIG = {
        # "always": always spend the clarification turn, evidence picks the question.
        # "evidence": ask only on an observed conflict/witness (or a trusted self-report).
        "ask_policy": "always",
        # Readings (interpretations) implemented when the task is ambiguous.
        "max_readings": 3,
        # Independent samples of the single reading when the task looks clear.
        "samples_when_clear": 2,
        # Probe inputs requested from the analysis step.
        "max_probes": 6,
        # Retries when a reply does not contain a usable ```python block.
        "repair_attempts": 2,
        # Treat divergence between samples of ONE reading as a witness (usually a bug).
        "ask_on_sample_divergence": False,
        # In "evidence" mode, also ask when the model reports a conflict/gap that
        # execution did not reproduce.
        "trust_self_reported_issue": True,
        # Execute candidates via env.exec_code; False skips execution entirely.
        "use_execution": True,
        # Global time limit (seconds) for the execution script inside the container.
        "exec_deadline_s": 20,
    }

    def run(self, env: ClarificationEnvironment, problem: dict[str, Any]) -> str:
        cfg = self.config
        entry_point = problem["entry_point"]
        prompt = problem["prompt"]
        fallback = _fence(_fill(FALLBACK_CODE_TEMPLATE, entry_point=entry_point))

        # 1. ANALYSE: goals, readings, probes.
        analysis = self.analyse(env, prompt, entry_point)

        # 2. IMPLEMENT one candidate per reading.
        candidates = self.implement(env, prompt, entry_point, analysis["readings"])

        # 3. EXECUTE all candidates on examples + probes in one container.
        examples = analysis["examples"]
        calls: list[tuple[str, str | None]] = [(e["call"], e["expected"]) for e in examples]
        calls += [(p, None) for p in analysis["probes"]]
        if cfg["use_execution"] and candidates and calls:
            _execute_all(env, candidates, calls, cfg["exec_deadline_s"])

        # 4. FILTER readings against the examples; look for a witness.
        survivors, conflict_example = _gricean_filter(candidates, len(examples))
        witnesses = (
            _find_witnesses(survivors, calls, not cfg["ask_on_sample_divergence"])
            if survivors
            else []
        )
        best = _best(survivors or candidates, len(examples)) if candidates else None

        # 5. DECIDE whether and what to ask.
        evidence, observed = _evidence(analysis, survivors, conflict_example, witnesses)
        # A bare self-reported issue is just a label; only trust it when the model
        # put its money where its mouth is by actually producing >=2 behaviourally
        # distinct readings, not merely asserting "gap"/"conflict".
        corroborated_self_report = (
            cfg["trust_self_reported_issue"]
            and analysis["issue"] in {"conflict", "gap"}
            and len(analysis["readings"]) >= 2
        )
        should_ask = cfg["ask_policy"] == "always" or observed or corroborated_self_report

        question = None
        if should_ask and env.can_ask():
            reply = _llm(
                env,
                _fill(QUESTION_TEMPLATE, entry_point=entry_point, prompt=prompt, evidence=evidence),
            )
            question = _parse_question(reply) or analysis["question"] or None

        answer = None
        if question:
            try:
                answer = env.ask_human(question)
            except TooManyQuestionException:
                answer = None

        # 6. RESOLVE: fresh solution from the answer, else the best reading.
        if answer is not None:
            final = _solve(
                env,
                _fill(
                    SOLVE_TEMPLATE,
                    entry_point=entry_point,
                    prompt=prompt,
                    question=question,
                    answer=answer,
                ),
                entry_point,
                cfg["repair_attempts"],
            )
            if final:
                return _fence(final)

        if best is not None:
            return _fence(best.code)

        code = _solve(
            env,
            _fill(
                IMPLEMENT_TEMPLATE, entry_point=entry_point, prompt=prompt, reading=DEFAULT_READING
            ),
            entry_point,
            cfg["repair_attempts"],
        )
        return _fence(code) if code else fallback

    # ------------------------------------------------------------------ #
    def analyse(
        self, env: ClarificationEnvironment, prompt: str, entry_point: str
    ) -> dict[str, Any]:
        raw = _llm(
            env,
            _fill(
                ANALYSE_TEMPLATE,
                prompt=prompt,
                entry_point=entry_point,
                max_probes=self.config["max_probes"],
            ),
        )
        data = _parse_json(raw)

        examples = [
            {"call": e["call"].strip(), "expected": e["expected"].strip()}
            for e in data.get("examples") or []
            if isinstance(e, dict)
            and _is_call(e.get("call"), entry_point)
            and _is_expr(e.get("expected"))
        ]
        readings = [
            r.strip() for r in data.get("readings") or [] if isinstance(r, str) and r.strip()
        ][: self.config["max_readings"]]
        probes = [p.strip() for p in data.get("probes") or [] if _is_call(p, entry_point)][
            : self.config["max_probes"]
        ]
        issue = str(data.get("issue", "none")).strip().lower()
        if issue not in {"none", "conflict", "gap", "ambiguity"}:
            issue = "none"
        question = str(data.get("question") or "").strip()

        return {
            "examples": examples,
            "readings": readings,
            "probes": probes,
            "issue": issue,
            "question": question,
        }

    def implement(
        self, env: ClarificationEnvironment, prompt: str, entry_point: str, readings: list[str]
    ) -> list[Candidate]:
        if len(readings) >= 2:
            plan = list(enumerate(readings))
        else:
            reading = readings[0] if readings else DEFAULT_READING
            plan = [(0, reading)] * max(1, self.config["samples_when_clear"])

        candidates: list[Candidate] = []
        for idx, reading in plan:
            code = _solve(
                env,
                _fill(
                    IMPLEMENT_TEMPLATE,
                    entry_point=entry_point,
                    prompt=prompt,
                    reading=reading,
                ),
                entry_point,
                self.config["repair_attempts"],
            )
            if code is not None:
                candidates.append(Candidate(code=code, reading=idx))
        return candidates
