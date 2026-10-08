"""Regression tests for clarify/algorithms/LAASeRAlgorithm.py.

These tests use a fake environment (no network, no Docker) so they can run
offline and for free. They exist to catch regressions in exception handling
that only manifest when the clarification/budget limits are hit, which the
30-task demo benchmark does not reliably exercise.
"""

from __future__ import annotations

import unittest

from clarify.algorithms.LAASeRAlgorithm import LAASeRAlgorithm
from clarify.env import LimitsExceededException, TooManyQuestionException

PROBLEM = {"prompt": "Write a function that adds two numbers.", "entry_point": "add"}


class _FakeEnv:
    """Minimal stand-in for ClarificationEnvironment exposing only llm/ask_human."""

    def __init__(self, llm_responses=None, llm_exception=None, ask_human_exception=None):
        self._llm_responses = list(llm_responses or [])
        self._llm_exception = llm_exception
        self._ask_human_exception = ask_human_exception

    def llm(self, messages):
        if self._llm_exception is not None:
            raise self._llm_exception
        return self._llm_responses.pop(0)

    def ask_human(self, query):
        if self._ask_human_exception is not None:
            raise self._ask_human_exception
        return "42"


class LAASeRExceptionHandlingTest(unittest.TestCase):
    def test_llm_budget_exceeded_returns_candidate_without_raising(self):
        env = _FakeEnv(llm_exception=LimitsExceededException("over budget"))
        result = LAASeRAlgorithm().run(env, PROBLEM)
        self.assertEqual(result, "")

    def test_clarification_budget_exceeded_returns_candidate_without_raising(self):
        env = _FakeEnv(
            llm_responses=["QUESTION: what should it return for empty input?"],
            ask_human_exception=TooManyQuestionException("too many questions"),
        )
        result = LAASeRAlgorithm().run(env, PROBLEM)
        self.assertEqual(result, "")

    def test_ready_to_code_returns_candidate(self):
        env = _FakeEnv(
            llm_responses=["READY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```"]
        )
        result = LAASeRAlgorithm().run(env, PROBLEM)
        self.assertIn("def add", result)


if __name__ == "__main__":
    unittest.main()
