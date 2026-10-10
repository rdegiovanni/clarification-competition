"""Regression tests for clarify/algorithms/laaser_gate_v3.py.

Offline, no network/Docker (same _FakeEnv pattern as tests/test_laaser_gate_v2.py). The new
mechanism vs. v2: instead of verifying a single self-picked assumption, the ALT+PROBE call may
return several candidate blocks (one per uncertain assumption), all probed in one combined
env.exec_code script, and the question asked belongs to the FIRST candidate (in listed order)
that shows a confirmed behavioral divergence -- not necessarily the first block in the response.
"""

from __future__ import annotations

import unittest

from clarify.algorithms.laaser_gate_v3 import LAASeR_GateV3
from clarify.env import LimitsExceededException, TooManyQuestionException

PROBLEM = {"prompt": "Write a function that adds two numbers.", "entry_point": "add"}

READY_ADD = "ASSUMPTIONS: none\nREADY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```"


def _block(assumption: str, alt_body: str, inputs: str, question: str) -> str:
    return (
        f"ASSUMPTION: {assumption}\n"
        f"ALTERNATIVE:\n```python\n{alt_body}\n```\n"
        f"INPUTS: {inputs}\n"
        f"QUESTION: {question}"
    )


BLOCK_1 = _block(
    "whether negatives are supported",
    "def add(a, b):\n    return abs(a) + abs(b)",
    "[(1, -2)]",
    "For add(1, -2), should the result be -1?",
)
BLOCK_2 = _block(
    "whether the inputs are always integers",
    "def add(a, b):\n    return int(a) + int(b)",
    "[(1.5, 2.5)]",
    "For add(1.5, 2.5), should the result be 4.0?",
)
BLOCK_3 = _block(
    "whether a third argument is expected",
    "def add(a, b):\n    return a + b + 1",
    "[(1, 2)]",
    "Should add(1, 2) return 3 or 4?",
)
MALFORMED_BLOCK = "ASSUMPTION: something\nno INPUTS section here"


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


class LAASeRGateV3Test(unittest.TestCase):
    def test_done_at_alt_probe_step_skips_exec_code(self):
        env = _FakeEnv(llm_responses=[READY_ADD, "DONE"])
        result = LAASeR_GateV3().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertEqual(env.exec_code_calls, 0)
        self.assertEqual(env.ask_human_calls, [])

    def test_only_second_candidate_diverges_asks_its_question(self):
        multi_response = "\n---\n".join([BLOCK_1, BLOCK_2, BLOCK_3])
        env = _FakeEnv(
            llm_responses=[READY_ADD, multi_response, READY_ADD, "DONE"],
            exec_code_responses=[
                "DIVERGE_0_0=False A=3 B=3\nDIVERGE_1_0=True A=4.0 B=4.0\nDIVERGE_2_0=True A=3 B=4"
            ],
        )
        result = LAASeR_GateV3().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertEqual(env.exec_code_calls, 1)
        self.assertEqual(len(env.ask_human_calls), 1)
        self.assertIn("1.5, 2.5", env.ask_human_calls[0])

    def test_no_candidate_diverges_returns_original_without_asking(self):
        multi_response = "\n---\n".join([BLOCK_1, BLOCK_2])
        env = _FakeEnv(
            llm_responses=[READY_ADD, multi_response],
            exec_code_responses=["DIVERGE_0_0=False A=3 B=3\nDIVERGE_1_0=False A=4.0 B=4.0"],
        )
        result = LAASeR_GateV3().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertEqual(env.exec_code_calls, 1)
        self.assertEqual(env.ask_human_calls, [])

    def test_malformed_middle_block_is_skipped_valid_ones_still_probed(self):
        multi_response = "\n---\n".join([BLOCK_1, MALFORMED_BLOCK, BLOCK_3])
        env = _FakeEnv(
            llm_responses=[READY_ADD, multi_response, READY_ADD, "DONE"],
            exec_code_responses=["DIVERGE_0_0=False A=3 B=3\nDIVERGE_1_0=True A=3 B=4"],
        )
        result = LAASeR_GateV3().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertEqual(env.exec_code_calls, 1)
        self.assertEqual(len(env.ask_human_calls), 1)
        self.assertIn("add(1, 2)", env.ask_human_calls[0])

    def test_more_than_three_blocks_only_first_three_considered(self):
        extra_block = _block(
            "a fourth assumption that should be ignored",
            "def add(a, b):\n    return a * b",
            "[(2, 3)]",
            "Should add(2, 3) return 6?",
        )
        multi_response = "\n---\n".join([BLOCK_1, BLOCK_2, BLOCK_3, extra_block])
        env = _FakeEnv(
            llm_responses=[READY_ADD, multi_response],
            exec_code_responses=[
                "DIVERGE_0_0=False A=3 B=3\nDIVERGE_1_0=False A=4.0 B=4.0\nDIVERGE_2_0=False A=3 B=3"
            ],
        )
        result = LAASeR_GateV3().run(env, PROBLEM)
        self.assertIn("def add", result)
        # the 4th (ignored) candidate would have diverged (2*3=6 != 2+3=5) -- if it had
        # been probed and asked about, ask_human would have been called. It must not be.
        self.assertEqual(env.ask_human_calls, [])

    def test_format_error_is_repaired_before_reaching_alt_probe(self):
        env = _FakeEnv(llm_responses=["not valid at all, no fence", READY_ADD, "DONE"])
        result = LAASeR_GateV3().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_invalid_entrypoint_is_repaired_before_reaching_alt_probe(self):
        env = _FakeEnv(
            llm_responses=[
                "ASSUMPTIONS: none\nREADY_TO_CODE\n```python\ndef wrong(a, b):\n    return a + b\n```",
                READY_ADD,
                "DONE",
            ]
        )
        result = LAASeR_GateV3().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_parsing_error_is_repaired_before_reaching_alt_probe(self):
        env = _FakeEnv(
            llm_responses=[
                "ASSUMPTIONS: none\nREADY_TO_CODE\n```python\ndef add(a, b)\n    return a + b\n```",
                READY_ADD,
                "DONE",
            ]
        )
        result = LAASeR_GateV3().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_llm_budget_exceeded_returns_empty_without_raising(self):
        env = _FakeEnv(llm_exception=LimitsExceededException("over budget"))
        result = LAASeR_GateV3().run(env, PROBLEM)
        self.assertEqual(result, "")

    def test_clarification_budget_exceeded_returns_candidate_seen_so_far(self):
        env = _FakeEnv(
            llm_responses=[READY_ADD, BLOCK_1],
            exec_code_responses=["DIVERGE_0_0=True A=-1 B=3"],
            ask_human_exception=TooManyQuestionException("too many questions"),
        )
        result = LAASeR_GateV3().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_never_ending_malformed_drafts_eventually_give_up_without_raising(self):
        env = _FakeEnv(llm_responses=["I am not sure what to do here."] * 20)
        result = LAASeR_GateV3().run(env, PROBLEM)
        self.assertEqual(result, "")
        self.assertLess(len(env.seen_prompts), 20)


if __name__ == "__main__":
    unittest.main()
