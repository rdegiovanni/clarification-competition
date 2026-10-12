"""Regression tests for clarify/algorithms/laaser_gate.py.

Offline, no network/Docker (same `_FakeEnv` pattern as tests/test_laaser_algorithm.py
and tests/test_laaser_repair_v2.py). `LAASeR_Gate` splits the champion's single
"decide to ask or code" call into a draft call (code + self-reported assumptions) and
a separate gate call (judges the draft+assumptions, asks at most one atomic question
or says DONE) -- these tests pin down that two-call flow plus the inherited
format/entry-point/parsing repair paths and the exception-safety fallbacks.
"""

from __future__ import annotations

import unittest

from clarify.algorithms.laaser_gate import LAASeR_Gate
from clarify.env import LimitsExceededException, TooManyQuestionException

PROBLEM = {"prompt": "Write a function that adds two numbers.", "entry_point": "add"}

READY_ADD = "ASSUMPTIONS: none\nREADY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```"


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


class LAASeRGateTest(unittest.TestCase):
    def test_draft_then_gate_done_returns_candidate(self):
        env = _FakeEnv(llm_responses=[READY_ADD, "DONE"])
        result = LAASeR_Gate().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_gate_asks_one_atomic_question_then_redrafts_to_done(self):
        env = _FakeEnv(
            llm_responses=[
                READY_ADD,
                "QUESTION: for add(2, 2), should the result be 4?",
                READY_ADD,
                "DONE",
            ]
        )
        result = LAASeR_Gate().run(env, PROBLEM)
        self.assertIn("def add", result)
        # the clarification must be glued onto the redraft prompt (the second DRAFT
        # call, index 2: draft, gate, redraft, gate) with a clear separator, not
        # smashed directly onto the task text.
        redraft_prompt = env.seen_prompts[2]
        self.assertIn("Clarifications:\n", redraft_prompt)
        self.assertIn("for add(2, 2)", redraft_prompt)

    def test_gate_question_with_colon_variant_is_parsed(self):
        env = _FakeEnv(
            llm_responses=[
                READY_ADD,
                "QUESTION:should it support floats?",
                READY_ADD,
                "DONE",
            ]
        )
        result = LAASeR_Gate().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_malformed_gate_response_falls_back_to_candidate(self):
        # Neither "DONE" nor "QUESTION:" -- must not loop forever and must not
        # discard the already-valid candidate.
        env = _FakeEnv(llm_responses=[READY_ADD, "I'm not sure what to output here."])
        result = LAASeR_Gate().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_format_error_is_repaired_before_reaching_the_gate(self):
        env = _FakeEnv(
            llm_responses=[
                "not valid at all, no fence",
                "READY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```",
                "DONE",
            ]
        )
        result = LAASeR_Gate().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_invalid_entrypoint_is_repaired_before_reaching_the_gate(self):
        env = _FakeEnv(
            llm_responses=[
                "ASSUMPTIONS: none\nREADY_TO_CODE\n```python\ndef wrong(a, b):\n    return a + b\n```",
                "READY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```",
                "DONE",
            ]
        )
        result = LAASeR_Gate().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_parsing_error_is_repaired_before_reaching_the_gate(self):
        env = _FakeEnv(
            llm_responses=[
                "ASSUMPTIONS: none\nREADY_TO_CODE\n```python\ndef add(a, b)\n    return a + b\n```",
                "READY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```",
                "DONE",
            ]
        )
        result = LAASeR_Gate().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_llm_budget_exceeded_returns_empty_without_raising(self):
        env = _FakeEnv(llm_exception=LimitsExceededException("over budget"))
        result = LAASeR_Gate().run(env, PROBLEM)
        self.assertEqual(result, "")

    def test_clarification_budget_exceeded_returns_candidate_seen_so_far(self):
        env = _FakeEnv(
            llm_responses=[READY_ADD, "QUESTION: for add(2, 2), should the result be 4?"],
            ask_human_exception=TooManyQuestionException("too many questions"),
        )
        result = LAASeR_Gate().run(env, PROBLEM)
        # a valid candidate was already drafted before the clarification budget
        # was exhausted -- it must not be discarded in favor of "".
        self.assertIn("def add", result)

    def test_never_ending_malformed_drafts_eventually_give_up_without_raising(self):
        env = _FakeEnv(llm_responses=["I am not sure what to do here."] * 20)
        result = LAASeR_Gate().run(env, PROBLEM)
        self.assertEqual(result, "")
        self.assertLess(len(env.seen_prompts), 20)


if __name__ == "__main__":
    unittest.main()
