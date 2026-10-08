"""Regression tests for clarify/algorithms/LAASeR2Algorithm.py.

Same rationale as tests/test_laaser_algorithm.py: a fake environment (no
network, no Docker) so budget/turn-limit and repair-loop edge cases that the
30-task demo benchmark may not reliably exercise are still covered.
"""

from __future__ import annotations

import unittest

from clarify.algorithms.LAASeR2Algorithm import MAX_REPAIR_ATTEMPTS, LAASeR2Algorithm
from clarify.env import LimitsExceededException, TooManyQuestionException

PROBLEM = {"prompt": "Write a function that adds two numbers.", "entry_point": "add"}
GOOD_SOLUTION = "```python\ndef add(a, b):\n    return a + b\n```"
WRONG_NAME_SOLUTION = "```python\ndef wrong(a, b):\n    return a + b\n```"


class _FakeEnv:
    """Minimal stand-in for ClarificationEnvironment exposing can_ask/llm/ask_human."""

    def __init__(self, llm_items=None, can_ask_value=True, ask_human_result="42", ask_human_exception=None):
        self._llm_items = list(llm_items or [])
        self._can_ask_value = can_ask_value
        self._ask_human_result = ask_human_result
        self._ask_human_exception = ask_human_exception

    def can_ask(self):
        return self._can_ask_value

    def llm(self, messages):
        item = self._llm_items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def ask_human(self, query):
        if self._ask_human_exception is not None:
            raise self._ask_human_exception
        return self._ask_human_result


class LAASeR2AlgorithmTest(unittest.TestCase):
    def test_no_question_then_solve_succeeds(self):
        env = _FakeEnv(llm_items=["NO_QUESTION", GOOD_SOLUTION])
        result = LAASeR2Algorithm().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_question_then_solve_succeeds(self):
        env = _FakeEnv(llm_items=["QUESTION: what about negative numbers?", GOOD_SOLUTION])
        result = LAASeR2Algorithm().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_wrong_entry_point_name_triggers_repair_then_succeeds(self):
        env = _FakeEnv(llm_items=["NO_QUESTION", WRONG_NAME_SOLUTION, GOOD_SOLUTION])
        result = LAASeR2Algorithm().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_repairs_exhausted_returns_named_fallback_not_wrong_name(self):
        env = _FakeEnv(
            llm_items=["NO_QUESTION"] + [WRONG_NAME_SOLUTION] * (MAX_REPAIR_ATTEMPTS + 1)
        )
        result = LAASeR2Algorithm().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertIn("NotImplementedError", result)

    def test_can_ask_false_skips_gate_straight_to_solve(self):
        env = _FakeEnv(llm_items=[GOOD_SOLUTION], can_ask_value=False)
        result = LAASeR2Algorithm().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_gate_budget_exceeded_still_solves(self):
        env = _FakeEnv(llm_items=[LimitsExceededException("over budget"), GOOD_SOLUTION])
        result = LAASeR2Algorithm().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_solve_budget_exceeded_returns_named_fallback(self):
        env = _FakeEnv(llm_items=["NO_QUESTION", LimitsExceededException("over budget")])
        result = LAASeR2Algorithm().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertIn("NotImplementedError", result)

    def test_too_many_questions_falls_back_to_no_clarification_and_still_solves(self):
        env = _FakeEnv(
            llm_items=["QUESTION: what about negative numbers?", GOOD_SOLUTION],
            ask_human_exception=TooManyQuestionException("too many questions"),
        )
        result = LAASeR2Algorithm().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_never_returns_empty_string(self):
        env = _FakeEnv(
            llm_items=["NO_QUESTION"] + [LimitsExceededException("x")]
        )
        result = LAASeR2Algorithm().run(env, PROBLEM)
        self.assertNotEqual(result, "")


if __name__ == "__main__":
    unittest.main()
