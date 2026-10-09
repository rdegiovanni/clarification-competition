"""Regression tests for clarify/algorithms/laaser_repair_v2.py.

Offline, no network/Docker (same `_FakeEnv` pattern as tests/test_laaser_algorithm.py).
These pin down the fixes v2 makes over LAASeR_Repair: a cap on repair attempts with
fallback to the best (syntactically-valid) candidate seen instead of "", explicit
handling of a response with neither READY_TO_CODE nor QUESTION, and a clean separator
before "Clarifications:".
"""

from __future__ import annotations

import unittest

from clarify.algorithms.laaser_repair_v2 import LAASeR_RepairV2
from clarify.env import LimitsExceededException, TooManyQuestionException

PROBLEM = {"prompt": "Write a function that adds two numbers.", "entry_point": "add"}


class _FakeEnv:
    """Minimal stand-in for ClarificationEnvironment exposing only llm/ask_human."""

    def __init__(self, llm_responses=None, llm_exception=None, ask_human_exception=None):
        self._llm_responses = list(llm_responses or [])
        self._llm_exception = llm_exception
        self._ask_human_exception = ask_human_exception
        self.seen_prompts: list[str] = []

    def llm(self, messages):
        self.seen_prompts.append(messages[0]["content"])
        if self._llm_exception is not None:
            raise self._llm_exception
        return self._llm_responses.pop(0)

    def ask_human(self, query):
        if self._ask_human_exception is not None:
            raise self._ask_human_exception
        return "42"


class RepairV2Test(unittest.TestCase):
    def test_ready_to_code_returns_candidate(self):
        env = _FakeEnv(
            llm_responses=["READY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```"]
        )
        result = LAASeR_RepairV2().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_question_then_answer_then_code(self):
        env = _FakeEnv(
            llm_responses=[
                "QUESTION: should it support floats?",
                "READY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```",
            ]
        )
        result = LAASeR_RepairV2().run(env, PROBLEM)
        self.assertIn("def add", result)
        # the clarification must be glued on with a clear separator, not smashed
        # directly onto the end of the task prompt text.
        self.assertIn("\n\nClarifications:\n", env.seen_prompts[-1])

    def test_llm_budget_exceeded_returns_empty_without_raising(self):
        env = _FakeEnv(llm_exception=LimitsExceededException("over budget"))
        result = LAASeR_RepairV2().run(env, PROBLEM)
        self.assertEqual(result, "")

    def test_clarification_budget_exceeded_returns_empty_without_raising(self):
        env = _FakeEnv(
            llm_responses=["QUESTION: what should it return for empty input?"],
            ask_human_exception=TooManyQuestionException("too many questions"),
        )
        result = LAASeR_RepairV2().run(env, PROBLEM)
        self.assertEqual(result, "")

    def test_response_without_any_keyword_eventually_gives_up_without_raising(self):
        # Every response is missing both READY_TO_CODE and QUESTION: the old
        # LAASeR_Repair looped on this forever (status never changes); v2 must
        # cap retries and give up cleanly instead of hanging/crashing.
        env = _FakeEnv(llm_responses=["I am not sure what to do here."] * 20)
        result = LAASeR_RepairV2().run(env, PROBLEM)
        self.assertEqual(result, "")
        self.assertLess(len(env.seen_prompts), 20)

    def test_falls_back_to_best_candidate_seen_instead_of_empty_string(self):
        # First attempt is syntactically valid Python but uses the wrong function
        # name (INVALID_ENTRYPOINT) and every repair attempt after that keeps
        # failing in a different way (format error) until attempts are exhausted.
        # v2 must return the earlier valid-but-wrong-named code, not "".
        env = _FakeEnv(
            llm_responses=[
                "READY_TO_CODE\n```python\ndef wrong_name(a, b):\n    return a + b\n```",
                "not valid at all, no fence",
                "not valid at all, no fence",
                "not valid at all, no fence",
                "not valid at all, no fence",
            ]
        )
        result = LAASeR_RepairV2().run(env, PROBLEM)
        self.assertIn("def wrong_name", result)

    def test_literal_question_word_inside_code_is_not_misread_as_a_question(self):
        # The response is a valid READY_TO_CODE answer whose code happens to
        # contain the bare word QUESTION in a comment, with no "QUESTION:"
        # clarifying-question marker. Must be treated as code, not a question.
        env = _FakeEnv(
            llm_responses=[
                "READY_TO_CODE\n```python\n"
                "def add(a, b):\n"
                "    # QUESTION about overflow is out of scope here\n"
                "    return a + b\n"
                "```"
            ]
        )
        result = LAASeR_RepairV2().run(env, PROBLEM)
        self.assertIn("def add", result)


if __name__ == "__main__":
    unittest.main()
