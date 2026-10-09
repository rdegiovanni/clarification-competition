"""Regression tests for clarify/algorithms/laaser_concretequestion.py.

Offline, no network/Docker (same `_FakeEnv` pattern as the other algorithm tests).
LAASeR_ConcreteQuestion is structurally identical to the champion LAASeR_Repair
(same repair loop, same format/entry-point/parsing-error recovery) with exactly
one intentional change: the generation prompt also tells the model to prefer a
concrete input/output example over an abstract definition when it does ask a
question. These tests pin down (a) the base control flow still matches the
champion's and (b) the concrete-example guidance is actually present in what
gets sent to the LLM.
"""

from __future__ import annotations

import unittest

from clarify.algorithms.laaser_concretequestion import LAASeR_ConcreteQuestion
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


class ConcreteQuestionTest(unittest.TestCase):
    def test_ready_to_code_returns_candidate(self):
        env = _FakeEnv(
            llm_responses=["READY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```"]
        )
        result = LAASeR_ConcreteQuestion().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_question_then_answer_then_code(self):
        env = _FakeEnv(
            llm_responses=[
                "QUESTION: should it support floats?",
                "READY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```",
            ]
        )
        result = LAASeR_ConcreteQuestion().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_llm_budget_exceeded_returns_empty_without_raising(self):
        env = _FakeEnv(llm_exception=LimitsExceededException("over budget"))
        result = LAASeR_ConcreteQuestion().run(env, PROBLEM)
        self.assertEqual(result, "")

    def test_clarification_budget_exceeded_returns_empty_without_raising(self):
        env = _FakeEnv(
            llm_responses=["QUESTION: what should it return for empty input?"],
            ask_human_exception=TooManyQuestionException("too many questions"),
        )
        result = LAASeR_ConcreteQuestion().run(env, PROBLEM)
        self.assertEqual(result, "")

    def test_invalid_entrypoint_triggers_repair_then_succeeds(self):
        env = _FakeEnv(
            llm_responses=[
                "READY_TO_CODE\n```python\ndef wrong_name(a, b):\n    return a + b\n```",
                "READY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```",
            ]
        )
        result = LAASeR_ConcreteQuestion().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_generation_prompt_contains_concrete_example_guidance(self):
        # This is the one intentional difference from the champion LAASeR_Repair:
        # the concrete-example-over-abstract-definition guidance must be present.
        env = _FakeEnv(
            llm_responses=["READY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```"]
        )
        LAASeR_ConcreteQuestion().run(env, PROBLEM)
        sent_prompt = env.seen_prompts[0]
        self.assertIn("concrete example", sent_prompt)
        self.assertIn("rather than an abstract description", sent_prompt)


if __name__ == "__main__":
    unittest.main()
