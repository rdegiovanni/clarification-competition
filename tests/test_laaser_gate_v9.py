"""Regression tests for clarify/algorithms/laaser_gate_v9.py.

Offline, no network/Docker (same _FakeEnv pattern as tests/test_laaser_gate_v7.py). Unlike every
Gate variant (v1-v7), this one does NOT add any new ask-decision mechanism: the single-call
decide-to-ask-or-code structure is the champion's own (unverified, low ask-rate), with only two
additive changes shown not to raise the ask rate on their own: (1) a nudge to prefer a concrete
example when it DOES ask (validated by laaser_concretequestion.py), and (2) a self-check-and-
repair step against the model's own stated EXAMPLES, which never asks a question, only repairs.
The self-check also validates each example's argument count against the candidate's own detected
signature before trusting it -- the fix for the corruption risk found in laaser_gate_v7.py.
"""

from __future__ import annotations

import unittest

from clarify.algorithms.laaser_gate_v9 import LAASeR_GateV9
from clarify.env import LimitsExceededException, TooManyQuestionException

PROBLEM = {"prompt": "Write a function that adds two numbers.", "entry_point": "add"}

NO_EXAMPLES_READY = (
    "EXAMPLES: none\nREADY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```"
)

PASSING_EXAMPLES_READY = (
    "EXAMPLES: [((2, 3), 5), ((1, 1), 2)]\n"
    "READY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```"
)

BUGGY_EXAMPLES_READY = (
    "EXAMPLES: [((2, 3), 5)]\nREADY_TO_CODE\n```python\ndef add(a, b):\n    return a - b\n```"
)

# Three args stated for a two-arg function -- the arg-count guard must drop this example
# rather than let a mismatched self-check corrupt an already-correct candidate.
MISMATCHED_ARITY_EXAMPLES_READY = (
    "EXAMPLES: [((1, 2, 3), 6)]\nREADY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```"
)

FIXED_REPAIR_RESPONSE = "READY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```"


class _FakeEnv:
    """Minimal stand-in for ClarificationEnvironment exposing llm/ask_human/exec_code."""

    def __init__(
        self,
        llm_responses=None,
        llm_exception=None,
        ask_human_exception=None,
        exec_code_responses=None,
    ):
        self._llm_responses = list(llm_responses or [])
        self._llm_exception = llm_exception
        self._ask_human_exception = ask_human_exception
        self._exec_code_responses = list(exec_code_responses or [])
        self.seen_prompts: list[str] = []
        self.exec_code_calls = 0
        self.ask_human_calls: list[str] = []

    def llm(self, messages):
        self.seen_prompts.append(messages[0]["content"])
        if self._llm_exception is not None:
            raise self._llm_exception
        return self._llm_responses.pop(0)

    def ask_human(self, query):
        self.ask_human_calls.append(query)
        if self._ask_human_exception is not None:
            raise self._ask_human_exception
        return "42"

    def exec_code(self, script):
        self.exec_code_calls += 1
        return self._exec_code_responses.pop(0)


class LAASeRGateV8Test(unittest.TestCase):
    def test_question_is_asked_immediately_with_no_verification_gate(self):
        # No ALT_PROBE, no exec_code-based gate -- a question is asked exactly like the
        # champion: directly, with no execution verification step in between.
        env = _FakeEnv(
            llm_responses=["QUESTION: for add(2, 2), should the result be 4?", NO_EXAMPLES_READY]
        )
        result = LAASeR_GateV9().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertEqual(len(env.ask_human_calls), 1)
        self.assertEqual(env.exec_code_calls, 0)

    def test_no_examples_skips_self_check(self):
        env = _FakeEnv(llm_responses=[NO_EXAMPLES_READY])
        result = LAASeR_GateV9().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertEqual(env.exec_code_calls, 0)
        self.assertEqual(env.ask_human_calls, [])

    def test_examples_all_pass_no_repair(self):
        env = _FakeEnv(
            llm_responses=[PASSING_EXAMPLES_READY],
            exec_code_responses=[
                "SELFCHECK_0=True actual=5 expected=5\nSELFCHECK_1=True actual=2 expected=2"
            ],
        )
        result = LAASeR_GateV9().run(env, PROBLEM)
        self.assertIn("return a + b", result)
        self.assertEqual(env.exec_code_calls, 1)
        self.assertEqual(env.ask_human_calls, [])

    def test_failing_example_triggers_repair_without_asking(self):
        env = _FakeEnv(
            llm_responses=[BUGGY_EXAMPLES_READY, FIXED_REPAIR_RESPONSE],
            exec_code_responses=[
                "SELFCHECK_0=False actual=-1 expected=5",
                "SELFCHECK_0=True actual=5 expected=5",
            ],
        )
        result = LAASeR_GateV9().run(env, PROBLEM)
        self.assertIn("return a + b", result)
        self.assertEqual(env.ask_human_calls, [])

    def test_mismatched_arity_example_is_discarded_not_trusted(self):
        # Candidate is already correct; a self-stated example with the wrong arg count must
        # be dropped by the guard, not used to "verify" (and corrupt) the candidate.
        env = _FakeEnv(llm_responses=[MISMATCHED_ARITY_EXAMPLES_READY])
        result = LAASeR_GateV9().run(env, PROBLEM)
        self.assertIn("return a + b", result)
        self.assertEqual(env.exec_code_calls, 0)

    def test_format_error_is_repaired_before_self_check(self):
        env = _FakeEnv(llm_responses=["not valid at all, no fence", NO_EXAMPLES_READY])
        result = LAASeR_GateV9().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_invalid_entrypoint_is_repaired(self):
        env = _FakeEnv(
            llm_responses=[
                "EXAMPLES: none\nREADY_TO_CODE\n```python\ndef wrong(a, b):\n    return a + b\n```",
                NO_EXAMPLES_READY,
            ]
        )
        result = LAASeR_GateV9().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_llm_budget_exceeded_returns_empty_without_raising(self):
        env = _FakeEnv(llm_exception=LimitsExceededException("over budget"))
        result = LAASeR_GateV9().run(env, PROBLEM)
        self.assertEqual(result, "")

    def test_clarification_budget_exceeded_returns_empty_without_raising(self):
        env = _FakeEnv(
            llm_responses=["QUESTION: what should it return for empty input?"],
            ask_human_exception=TooManyQuestionException("too many questions"),
        )
        result = LAASeR_GateV9().run(env, PROBLEM)
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
