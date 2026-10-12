"""Regression tests for clarify/algorithms/laaser_gate_v2.py.

Offline, no network/Docker (same `_FakeEnv` pattern as tests/test_laaser_gate.py), extended with
an `exec_code` stub since `LAASeR_GateV2` is the first of our own algorithms to use it. The new
mechanism vs. v1: instead of trusting the model's own "this assumption is critical" self-report,
an ALT+PROBE call drafts an alternative candidate and a set of probe inputs, and the two
candidates are actually run (via env.exec_code) on those inputs. Only a confirmed behavioral
divergence results in a question being asked; otherwise the draft candidate is returned as-is,
even if the model's own ALT+PROBE response claimed something was critical.
"""

from __future__ import annotations

import unittest

from clarify.algorithms.laaser_gate_v2 import LAASeR_GateV2
from clarify.env import LimitsExceededException, TooManyQuestionException

PROBLEM = {"prompt": "Write a function that adds two numbers.", "entry_point": "add"}

READY_ADD = "ASSUMPTIONS: none\nREADY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```"

ALT_RESPONSE = (
    "ASSUMPTION: whether negative numbers are supported\n"
    "ALTERNATIVE:\n```python\ndef add(a, b):\n    return abs(a) + abs(b)\n```\n"
    "INPUTS: [(1, -2)]\n"
    "QUESTION: For add(1, -2), should the result be -1?"
)


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


class LAASeRGateV2Test(unittest.TestCase):
    def test_done_at_alt_probe_step_skips_exec_code(self):
        env = _FakeEnv(llm_responses=[READY_ADD, "DONE"])
        result = LAASeR_GateV2().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertEqual(env.exec_code_calls, 0)
        self.assertEqual(env.ask_human_calls, [])

    def test_confirmed_divergence_asks_the_predrafted_question(self):
        env = _FakeEnv(
            llm_responses=[READY_ADD, ALT_RESPONSE, READY_ADD, "DONE"],
            exec_code_responses=["DIVERGE_0=True A=-1 B=3"],
        )
        result = LAASeR_GateV2().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertEqual(env.exec_code_calls, 1)
        self.assertEqual(len(env.ask_human_calls), 1)
        self.assertIn("add(1, -2)", env.ask_human_calls[0])
        redraft_prompt = env.seen_prompts[2]
        self.assertIn("Clarifications:\n", redraft_prompt)

    def test_no_divergence_returns_original_candidate_without_asking(self):
        # The ALT+PROBE call claims the assumption is critical, but running both
        # candidates on the probe input shows they agree -- must NOT ask.
        env = _FakeEnv(
            llm_responses=[READY_ADD, ALT_RESPONSE],
            exec_code_responses=["DIVERGE_0=False A=3 B=3"],
        )
        result = LAASeR_GateV2().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertEqual(env.exec_code_calls, 1)
        self.assertEqual(env.ask_human_calls, [])

    def test_malformed_alt_response_falls_back_to_candidate_without_asking(self):
        env = _FakeEnv(llm_responses=[READY_ADD, "ASSUMPTION: something\nno INPUTS section here"])
        result = LAASeR_GateV2().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertEqual(env.exec_code_calls, 0)
        self.assertEqual(env.ask_human_calls, [])

    def test_non_literal_inputs_falls_back_to_candidate_without_asking(self):
        bad_response = (
            "ASSUMPTION: x\nALTERNATIVE:\n```python\ndef add(a, b):\n    return a - b\n```\n"
            "INPUTS: [add(1, 2)]\n"
            "QUESTION: should it be negative?"
        )
        env = _FakeEnv(llm_responses=[READY_ADD, bad_response])
        result = LAASeR_GateV2().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertEqual(env.exec_code_calls, 0)
        self.assertEqual(env.ask_human_calls, [])

    def test_format_error_is_repaired_before_reaching_alt_probe(self):
        env = _FakeEnv(
            llm_responses=["not valid at all, no fence", READY_ADD, "DONE"],
        )
        result = LAASeR_GateV2().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_invalid_entrypoint_is_repaired_before_reaching_alt_probe(self):
        env = _FakeEnv(
            llm_responses=[
                "ASSUMPTIONS: none\nREADY_TO_CODE\n```python\ndef wrong(a, b):\n    return a + b\n```",
                READY_ADD,
                "DONE",
            ]
        )
        result = LAASeR_GateV2().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_parsing_error_is_repaired_before_reaching_alt_probe(self):
        env = _FakeEnv(
            llm_responses=[
                "ASSUMPTIONS: none\nREADY_TO_CODE\n```python\ndef add(a, b)\n    return a + b\n```",
                READY_ADD,
                "DONE",
            ]
        )
        result = LAASeR_GateV2().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_llm_budget_exceeded_returns_empty_without_raising(self):
        env = _FakeEnv(llm_exception=LimitsExceededException("over budget"))
        result = LAASeR_GateV2().run(env, PROBLEM)
        self.assertEqual(result, "")

    def test_clarification_budget_exceeded_returns_candidate_seen_so_far(self):
        env = _FakeEnv(
            llm_responses=[READY_ADD, ALT_RESPONSE],
            exec_code_responses=["DIVERGE_0=True A=-1 B=3"],
            ask_human_exception=TooManyQuestionException("too many questions"),
        )
        result = LAASeR_GateV2().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_never_ending_malformed_drafts_eventually_give_up_without_raising(self):
        env = _FakeEnv(llm_responses=["I am not sure what to do here."] * 20)
        result = LAASeR_GateV2().run(env, PROBLEM)
        self.assertEqual(result, "")
        self.assertLess(len(env.seen_prompts), 20)


if __name__ == "__main__":
    unittest.main()
