"""Regression tests for clarify/algorithms/laaser_gate_v7.py.

Offline, no network/Docker (same _FakeEnv pattern as tests/test_laaser_gate_v3.py). The new
mechanism vs. v3: alongside ASSUMPTIONS, the DRAFT step also states 2-3 concrete (args, expected)
pairs it believes its OWN implementation must satisfy -- for every task, not just ones whose
prompt happens to contain worked examples (that version was correctly flagged as too narrow to
generalize). The candidate is then run against its own stated examples via env.exec_code; a
mismatch is unambiguous evidence of an implementation bug (the model's stated intent disagrees
with its own code), fixed with one targeted repair call rather than a clarifying question. This
never touches the clarification budget and is orthogonal to v3's unchanged ALT_PROBE mechanism,
which still runs afterward on whatever candidate results.
"""

from __future__ import annotations

import unittest

from clarify.algorithms.laaser_gate_v7 import LAASeR_GateV7
from clarify.env import LimitsExceededException

PROBLEM = {"prompt": "Write a function that adds two numbers.", "entry_point": "add"}

NO_EXAMPLES_DRAFT = "ASSUMPTIONS: none\nEXAMPLES: none\nREADY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```"

PASSING_EXAMPLES_DRAFT = (
    "ASSUMPTIONS: none\n"
    "EXAMPLES: [((2, 3), 5), ((1, 1), 2)]\n"
    "READY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```"
)

BUGGY_EXAMPLES_DRAFT = (
    "ASSUMPTIONS: none\n"
    "EXAMPLES: [((2, 3), 5)]\n"
    "READY_TO_CODE\n```python\ndef add(a, b):\n    return a - b\n```"
)

MALFORMED_EXAMPLES_DRAFT = (
    "ASSUMPTIONS: none\n"
    "EXAMPLES: [add(2, 3)]\n"  # not a literal, must be ignored rather than crash
    "READY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```"
)

FIXED_REPAIR_RESPONSE = "READY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```"
STILL_BUGGY_REPAIR_RESPONSE = "READY_TO_CODE\n```python\ndef add(a, b):\n    return a * b\n```"


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


class LAASeRGateV7Test(unittest.TestCase):
    def test_no_examples_skips_self_check_entirely(self):
        env = _FakeEnv(llm_responses=[NO_EXAMPLES_DRAFT, "DONE"])
        result = LAASeR_GateV7().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertEqual(env.exec_code_calls, 0)

    def test_examples_all_pass_no_repair_needed(self):
        env = _FakeEnv(
            llm_responses=[PASSING_EXAMPLES_DRAFT, "DONE"],
            exec_code_responses=[
                "SELFCHECK_0=True actual=5 expected=5\nSELFCHECK_1=True actual=2 expected=2"
            ],
        )
        result = LAASeR_GateV7().run(env, PROBLEM)
        self.assertIn("return a + b", result)
        self.assertEqual(env.exec_code_calls, 1)

    def test_failing_example_triggers_repair_without_asking(self):
        env = _FakeEnv(
            llm_responses=[BUGGY_EXAMPLES_DRAFT, FIXED_REPAIR_RESPONSE, "DONE"],
            exec_code_responses=[
                "SELFCHECK_0=False actual=-1 expected=5",
                "SELFCHECK_0=True actual=5 expected=5",
            ],
        )
        result = LAASeR_GateV7().run(env, PROBLEM)
        self.assertIn("return a + b", result)
        self.assertEqual(env.exec_code_calls, 2)
        self.assertEqual(env.ask_human_calls, [])

    def test_repair_exhausted_gives_up_without_crashing(self):
        env = _FakeEnv(
            llm_responses=[
                BUGGY_EXAMPLES_DRAFT,
                STILL_BUGGY_REPAIR_RESPONSE,
                STILL_BUGGY_REPAIR_RESPONSE,
                "DONE",
            ],
            exec_code_responses=[
                "SELFCHECK_0=False actual=-1 expected=5",
                "SELFCHECK_0=False actual=6 expected=5",
                "SELFCHECK_0=False actual=6 expected=5",
            ],
        )
        result = LAASeR_GateV7().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertEqual(env.ask_human_calls, [])

    def test_malformed_examples_falls_back_to_no_self_check(self):
        env = _FakeEnv(llm_responses=[MALFORMED_EXAMPLES_DRAFT, "DONE"])
        result = LAASeR_GateV7().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertEqual(env.exec_code_calls, 0)

    def test_alt_probe_still_runs_after_self_check(self):
        alt_block = (
            "ASSUMPTION: whether negatives are supported\n"
            "ALTERNATIVE:\n```python\ndef add(a, b):\n    return abs(a) + abs(b)\n```\n"
            "INPUTS: [(1, -2)]\n"
            "QUESTION: For add(1, -2), should the result be -1?"
        )
        env = _FakeEnv(
            llm_responses=[PASSING_EXAMPLES_DRAFT, alt_block],
            exec_code_responses=[
                "SELFCHECK_0=True actual=5 expected=5\nSELFCHECK_1=True actual=2 expected=2",
                "DIVERGE_0_0=False A=3 B=3",
            ],
        )
        result = LAASeR_GateV7().run(env, PROBLEM)
        self.assertIn("return a + b", result)
        self.assertEqual(env.ask_human_calls, [])

    def test_format_error_is_repaired_before_self_check(self):
        env = _FakeEnv(llm_responses=["not valid at all, no fence", NO_EXAMPLES_DRAFT, "DONE"])
        result = LAASeR_GateV7().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_invalid_entrypoint_is_repaired_before_self_check(self):
        env = _FakeEnv(
            llm_responses=[
                "ASSUMPTIONS: none\nEXAMPLES: none\nREADY_TO_CODE\n```python\ndef wrong(a, b):\n    return a + b\n```",
                NO_EXAMPLES_DRAFT,
                "DONE",
            ]
        )
        result = LAASeR_GateV7().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_llm_budget_exceeded_returns_empty_without_raising(self):
        env = _FakeEnv(llm_exception=LimitsExceededException("over budget"))
        result = LAASeR_GateV7().run(env, PROBLEM)
        self.assertEqual(result, "")

    def test_never_ending_malformed_drafts_eventually_give_up_without_raising(self):
        env = _FakeEnv(llm_responses=["I am not sure what to do here."] * 20)
        result = LAASeR_GateV7().run(env, PROBLEM)
        self.assertEqual(result, "")
        self.assertLess(len(env.seen_prompts), 20)


if __name__ == "__main__":
    unittest.main()
