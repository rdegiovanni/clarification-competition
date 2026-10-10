"""Regression tests for clarify/algorithms/laaser_gate_v4.py.

Offline, no network/Docker (same _FakeEnv pattern as tests/test_laaser_gate_v3.py). The new
mechanism vs. v3: a deterministic, AST-based structural check runs once right after the first
successful draft, before the self-reported ALT+PROBE step. If the drafted candidate takes exactly
one argument that is used like a sequence (len(), indexing, iteration) AND the task prompt shows
no function stub at all, a fixed, pre-written, atomic question about the signature is asked
directly -- no extra LLM call, no env.exec_code call, no dependency on the model's own
self-reported ASSUMPTIONS list ever mentioning it (which Mbpp/229's analysis showed it never does
for this kind of prompt).
"""

from __future__ import annotations

import unittest

from clarify.algorithms.laaser_gate_v4 import LAASeR_GateV4
from clarify.env import LimitsExceededException, TooManyQuestionException

PROBLEM = {"prompt": "Write a function that adds two numbers.", "entry_point": "add"}
READY_ADD = "ASSUMPTIONS: none\nREADY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```"

PROBLEM_SEQ_NO_STUB = {
    "prompt": "Write a function to count the items.",
    "entry_point": "count_items",
}
DRAFT_SEQ = (
    "ASSUMPTIONS: none\nREADY_TO_CODE\n```python\ndef count_items(arr):\n    return len(arr)\n```"
)

PROBLEM_SEQ_WITH_STUB = {
    "prompt": "def count_items(arr):\n    # count the items\n    pass",
    "entry_point": "count_items",
}

PROBLEM_NON_SEQ_SINGLE_ARG = {
    "prompt": "Write a function that increments a number.",
    "entry_point": "inc",
}
DRAFT_NON_SEQ = "ASSUMPTIONS: none\nREADY_TO_CODE\n```python\ndef inc(x):\n    return x + 1\n```"


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


class LAASeRGateV4Test(unittest.TestCase):
    def test_forced_signature_check_asks_before_alt_probe(self):
        env = _FakeEnv(llm_responses=[DRAFT_SEQ, DRAFT_SEQ, "DONE"])
        result = LAASeR_GateV4().run(env, PROBLEM_SEQ_NO_STUB)
        self.assertIn("def count_items", result)
        self.assertEqual(len(env.ask_human_calls), 1)
        self.assertIn("count_items", env.ask_human_calls[0])
        self.assertIn("arr", env.ask_human_calls[0])
        self.assertEqual(env.exec_code_calls, 0)

    def test_forced_check_does_not_trigger_when_stub_shown(self):
        env = _FakeEnv(llm_responses=[DRAFT_SEQ, "DONE"])
        result = LAASeR_GateV4().run(env, PROBLEM_SEQ_WITH_STUB)
        self.assertIn("def count_items", result)
        self.assertEqual(env.ask_human_calls, [])

    def test_forced_check_does_not_trigger_for_multi_param_candidate(self):
        env = _FakeEnv(llm_responses=[READY_ADD, "DONE"])
        result = LAASeR_GateV4().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertEqual(env.ask_human_calls, [])

    def test_forced_check_does_not_trigger_for_non_sequence_single_arg(self):
        env = _FakeEnv(llm_responses=[DRAFT_NON_SEQ, "DONE"])
        result = LAASeR_GateV4().run(env, PROBLEM_NON_SEQ_SINGLE_ARG)
        self.assertIn("def inc", result)
        self.assertEqual(env.ask_human_calls, [])

    def test_forced_check_only_fires_once_per_run(self):
        # After answering, the redraft is still a single-arg sequence candidate (the fake
        # human's answer doesn't actually change the draft) -- the forced check must not
        # fire a second time; it should fall through straight to ALT_PROBE on the redraft.
        env = _FakeEnv(llm_responses=[DRAFT_SEQ, DRAFT_SEQ, "DONE"])
        LAASeR_GateV4().run(env, PROBLEM_SEQ_NO_STUB)
        self.assertEqual(len(env.ask_human_calls), 1)

    def test_alt_probe_still_works_when_forced_check_does_not_trigger(self):
        alt_block = (
            "ASSUMPTION: whether negatives are supported\n"
            "ALTERNATIVE:\n```python\ndef add(a, b):\n    return abs(a) + abs(b)\n```\n"
            "INPUTS: [(1, -2)]\n"
            "QUESTION: For add(1, -2), should the result be -1?"
        )
        env = _FakeEnv(
            llm_responses=[READY_ADD, alt_block, READY_ADD, "DONE"],
            exec_code_responses=["DIVERGE_0_0=True A=-1 B=3"],
        )
        result = LAASeR_GateV4().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertEqual(len(env.ask_human_calls), 1)
        self.assertIn("add(1, -2)", env.ask_human_calls[0])

    def test_format_error_is_repaired_before_reaching_forced_check(self):
        env = _FakeEnv(llm_responses=["not valid at all, no fence", READY_ADD, "DONE"])
        result = LAASeR_GateV4().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_invalid_entrypoint_is_repaired_before_reaching_forced_check(self):
        env = _FakeEnv(
            llm_responses=[
                "ASSUMPTIONS: none\nREADY_TO_CODE\n```python\ndef wrong(a, b):\n    return a + b\n```",
                READY_ADD,
                "DONE",
            ]
        )
        result = LAASeR_GateV4().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_parsing_error_is_repaired_before_reaching_forced_check(self):
        env = _FakeEnv(
            llm_responses=[
                "ASSUMPTIONS: none\nREADY_TO_CODE\n```python\ndef add(a, b)\n    return a + b\n```",
                READY_ADD,
                "DONE",
            ]
        )
        result = LAASeR_GateV4().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_llm_budget_exceeded_returns_empty_without_raising(self):
        env = _FakeEnv(llm_exception=LimitsExceededException("over budget"))
        result = LAASeR_GateV4().run(env, PROBLEM)
        self.assertEqual(result, "")

    def test_clarification_budget_exceeded_returns_candidate_seen_so_far(self):
        env = _FakeEnv(
            llm_responses=[DRAFT_SEQ],
            ask_human_exception=TooManyQuestionException("too many questions"),
        )
        result = LAASeR_GateV4().run(env, PROBLEM_SEQ_NO_STUB)
        self.assertIn("def count_items", result)

    def test_never_ending_malformed_drafts_eventually_give_up_without_raising(self):
        env = _FakeEnv(llm_responses=["I am not sure what to do here."] * 20)
        result = LAASeR_GateV4().run(env, PROBLEM)
        self.assertEqual(result, "")
        self.assertLess(len(env.seen_prompts), 20)


if __name__ == "__main__":
    unittest.main()
