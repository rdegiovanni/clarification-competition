"""Regression tests for clarify/algorithms/laaser_formal_verified.py.

Offline, no network/Docker (same _FakeEnv pattern as tests/test_laaser_formal.py, with a second
exec_code call now possible per task: the SAT check, then -- only on the AMBIGUOUS path -- the
divergence probe). Most tests feed exec_code canned output to isolate the ASK/CODE decision from
the scripts themselves; a few use real_exec_code=True so both the SAT and divergence-probe scripts
actually execute via Python's own exec(), through the public run() API, no private imports.
"""

from __future__ import annotations

import contextlib
import io
import unittest

from clarify.algorithms.laaser_formal_verified import LAASeR_FormalVerified
from clarify.env import LimitsExceededException, TooManyQuestionException

PROBLEM = {"prompt": "Write a function that scales a number.", "entry_point": "scale"}

GOOD_CODE = "```python\ndef scale(x):\n    return x * 2\n```"
WRONG_NAME_CODE = "```python\ndef mul(x):\n    return x * 2\n```"
BROKEN_CODE = "```python\ndef scale(x)\n    return x * 2\n```"

NO_DEFECTS_CODE = 'FORMALIZATION: {"defects": [], "clauses": []}\nDECISION: CODE\n' + GOOD_CODE

ONE_ATOM_CONTRADICTION = (
    'FORMALIZATION: {"defects": [{"atom": "scale_mode", '
    '"phrase": "doubles the input but also triples the input", '
    '"reading_true": "it doubles the input", "reading_false": "it triples the input", '
    '"baseline": True}], "clauses": [["scale_mode"], ["-scale_mode"]]}\n'
    "DECISION: CODE\n" + GOOD_CODE
)

ONE_ATOM_NO_CLAUSE = (
    'FORMALIZATION: {"defects": [{"atom": "scale_mode", "phrase": "not stated", '
    '"reading_true": "it doubles the input", "reading_false": "it triples the input", '
    '"baseline": True}], "clauses": []}\n'
    "DECISION: CODE\n" + GOOD_CODE
)

ONE_ATOM_DETERMINED = (
    'FORMALIZATION: {"defects": [{"atom": "scale_mode", "phrase": "always doubles", '
    '"reading_true": "it doubles the input", "reading_false": "it triples the input", '
    '"baseline": True}], "clauses": [["scale_mode"]]}\n'
    "DECISION: CODE\n" + GOOD_CODE
)

DIVERGING_PROBE_RESPONSE = (
    "CANDIDATE_A:\n```python\ndef scale(x):\n    return x * 2\n```\n"
    "CANDIDATE_B:\n```python\ndef scale(x):\n    return x * 3\n```\n"
    "INPUTS: [(2,), (5,)]\n"
)

NONDIVERGING_PROBE_RESPONSE = (
    "CANDIDATE_A:\n```python\ndef scale(x):\n    return x * 2\n```\n"
    "CANDIDATE_B:\n```python\ndef scale(x):\n    return x * 2\n```\n"
    "INPUTS: [(2,), (5,)]\n"
)

GARBAGE_PROBE_RESPONSE = "I could not come up with two candidates for this task."


class _FakeEnv:
    """Minimal stand-in for ClarificationEnvironment exposing llm/ask_human/can_ask/exec_code."""

    def __init__(
        self,
        llm_responses=None,
        llm_exception=None,
        ask_human_exception=None,
        can_ask=True,
        answer="It doubles the input.",
        exec_code_responses=None,
        real_exec_code=False,
    ):
        self._llm_responses = list(llm_responses or [])
        self._llm_exception = llm_exception
        self._ask_human_exception = ask_human_exception
        self._can_ask = can_ask
        self._answer = answer
        self._exec_code_responses = list(exec_code_responses or [])
        self._real_exec_code = real_exec_code
        self.seen_prompts: list[str] = []
        self.ask_human_calls: list[str] = []
        self.exec_code_calls = 0

    def llm(self, messages):
        content = messages if isinstance(messages, str) else messages[-1]["content"]
        self.seen_prompts.append(content)
        if self._llm_exception is not None:
            raise self._llm_exception
        return self._llm_responses.pop(0)

    def can_ask(self):
        return self._can_ask

    def ask_human(self, query):
        self.ask_human_calls.append(query)
        if self._ask_human_exception is not None:
            raise self._ask_human_exception
        return self._answer

    def exec_code(self, script):
        self.exec_code_calls += 1
        if self._real_exec_code:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                exec(script, {})  # noqa: S102 -- trusted, test-local script
            return buf.getvalue()
        return self._exec_code_responses.pop(0)


class LAASeRFormalVerifiedTest(unittest.TestCase):
    def test_zero_defects_codes_directly_without_asking_or_exec(self):
        env = _FakeEnv(llm_responses=[NO_DEFECTS_CODE])
        result = LAASeR_FormalVerified().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.ask_human_calls, [])
        self.assertEqual(env.exec_code_calls, 0)

    def test_unsat_asks_immediately_without_a_divergence_probe(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_CONTRADICTION, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=UNSAT"],
        )
        result = LAASeR_FormalVerified().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.exec_code_calls, 1)  # SAT check only, no probe
        self.assertEqual(len(env.ask_human_calls), 1)
        self.assertEqual(len(env.seen_prompts), 2)  # FORMALIZE, CODE -- no probe-build call

    def test_determined_codes_without_asking_or_probing(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_DETERMINED, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=DETERMINED"],
        )
        result = LAASeR_FormalVerified().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.exec_code_calls, 1)
        self.assertEqual(env.ask_human_calls, [])

    def test_ambiguous_with_real_divergence_asks(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_NO_CLAUSE, DIVERGING_PROBE_RESPONSE, GOOD_CODE],
            exec_code_responses=[
                "SAT_RESULT=AMBIGUOUS atoms=['scale_mode']",
                "DIVERGE_0=True\nDIVERGE_1=True",
            ],
        )
        result = LAASeR_FormalVerified().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.exec_code_calls, 2)
        self.assertEqual(len(env.ask_human_calls), 1)
        self.assertIn("it doubles the input", env.ask_human_calls[0])
        self.assertIn("it triples the input", env.ask_human_calls[0])

    def test_ambiguous_with_no_divergence_skips_the_question(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_NO_CLAUSE, NONDIVERGING_PROBE_RESPONSE, GOOD_CODE],
            exec_code_responses=[
                "SAT_RESULT=AMBIGUOUS atoms=['scale_mode']",
                "DIVERGE_0=False\nDIVERGE_1=False",
            ],
        )
        result = LAASeR_FormalVerified().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.exec_code_calls, 2)
        self.assertEqual(env.ask_human_calls, [])
        code_prompt = env.seen_prompts[-1]
        self.assertIn("it doubles the input", code_prompt)  # baseline=True -> reading_true

    def test_ambiguous_with_unparseable_probe_falls_back_to_asking(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_NO_CLAUSE, GARBAGE_PROBE_RESPONSE, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=AMBIGUOUS atoms=['scale_mode']"],
        )
        result = LAASeR_FormalVerified().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.exec_code_calls, 1)  # SAT check only; probe never reaches exec_code
        self.assertEqual(len(env.ask_human_calls), 1)

    def test_no_ask_when_budget_is_exhausted(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_NO_CLAUSE, DIVERGING_PROBE_RESPONSE, GOOD_CODE],
            exec_code_responses=[
                "SAT_RESULT=AMBIGUOUS atoms=['scale_mode']",
                "DIVERGE_0=True\nDIVERGE_1=True",
            ],
            can_ask=False,
        )
        result = LAASeR_FormalVerified().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.ask_human_calls, [])

    def test_too_many_questions_still_produces_code(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_CONTRADICTION, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=UNSAT"],
            ask_human_exception=TooManyQuestionException("limit"),
        )
        result = LAASeR_FormalVerified().run(env, PROBLEM)
        self.assertIn("def scale", result)

    def test_limits_exceeded_on_first_call_returns_empty_without_crashing(self):
        env = _FakeEnv(llm_exception=LimitsExceededException("budget"))
        self.assertEqual(LAASeR_FormalVerified().run(env, PROBLEM), "")

    def test_wrong_entry_point_is_repaired(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_CONTRADICTION, WRONG_NAME_CODE, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=UNSAT"],
        )
        result = LAASeR_FormalVerified().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertIn("named exactly `scale`", env.seen_prompts[2])

    def test_unrepairable_entry_point_falls_back_to_alias(self):
        env = _FakeEnv(
            llm_responses=[
                ONE_ATOM_CONTRADICTION,
                WRONG_NAME_CODE,
                WRONG_NAME_CODE,
                WRONG_NAME_CODE,
            ],
            exec_code_responses=["SAT_RESULT=UNSAT"],
        )
        result = LAASeR_FormalVerified().run(env, PROBLEM)
        self.assertIn("def mul(x)", result)
        self.assertTrue(result.rstrip().endswith("scale = mul"))
        namespace: dict = {}
        exec(result, namespace)  # noqa: S102 -- trusted, test-local code
        self.assertEqual(namespace["scale"](3), 6)

    def test_syntax_error_in_code_decision_is_repaired(self):
        env = _FakeEnv(llm_responses=["DECISION: CODE\n" + BROKEN_CODE, GOOD_CODE])
        result = LAASeR_FormalVerified().run(env, PROBLEM)
        self.assertEqual(result.strip(), "def scale(x):\n    return x * 2")
        self.assertIn("not valid Python", env.seen_prompts[1])

    # -- Real execution of both generated scripts, through the public API --

    def test_real_scripts_detect_divergence_and_ask(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_NO_CLAUSE, DIVERGING_PROBE_RESPONSE, GOOD_CODE],
            real_exec_code=True,
        )
        LAASeR_FormalVerified().run(env, PROBLEM)
        self.assertEqual(env.exec_code_calls, 2)
        self.assertEqual(len(env.ask_human_calls), 1)

    def test_real_scripts_detect_no_divergence_and_skip_asking(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_NO_CLAUSE, NONDIVERGING_PROBE_RESPONSE, GOOD_CODE],
            real_exec_code=True,
        )
        LAASeR_FormalVerified().run(env, PROBLEM)
        self.assertEqual(env.exec_code_calls, 2)
        self.assertEqual(env.ask_human_calls, [])


if __name__ == "__main__":
    unittest.main()
