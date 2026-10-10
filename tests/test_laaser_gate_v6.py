"""Regression tests for clarify/algorithms/laaser_gate_v6.py.

Offline, no network/Docker (same _FakeEnv pattern as tests/test_laaser_gate_v3.py). The new
mechanism vs. v3: instead of one DRAFT call, three independent DRAFT calls are made (same
prompt, same env-fixed temperature -- env.llm has no per-call temperature override, so the
diversity comes from repeated sampling, not from varying temperature). Their ASSUMPTIONS lists
are unioned and fed into the same execution-verified multi-hypothesis ALT_PROBE step v3 already
uses, unchanged. The first successfully-parsed draft is used as the base candidate; drafts that
fail to parse (even after their own repair attempts) are simply dropped from the pool rather than
failing the whole round, as long as at least one draft succeeds.
"""

from __future__ import annotations

import unittest

from clarify.algorithms.laaser_gate_v6 import LAASeR_GateV6
from clarify.env import LimitsExceededException, TooManyQuestionException

PROBLEM = {"prompt": "Write a function that adds two numbers.", "entry_point": "add"}


def _draft(assumption: str = "none") -> str:
    return f"ASSUMPTIONS: {assumption}\nREADY_TO_CODE\n```python\ndef add(a, b):\n    return a + b\n```"


ALT_BLOCK = (
    "ASSUMPTION: whether negatives are supported\n"
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


class LAASeRGateV6Test(unittest.TestCase):
    def test_three_clean_drafts_then_done_returns_first_candidate(self):
        env = _FakeEnv(
            llm_responses=[_draft("A"), _draft("B"), _draft("C"), "DONE"],
        )
        result = LAASeR_GateV6().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertEqual(env.exec_code_calls, 0)
        self.assertEqual(env.ask_human_calls, [])

    def test_assumptions_from_all_three_drafts_reach_the_alt_probe_prompt(self):
        env = _FakeEnv(
            llm_responses=[
                _draft("floats are not supported"),
                _draft("overflow is not handled"),
                _draft("inputs are always integers"),
            ]
            + ["DONE"],
        )
        LAASeR_GateV6().run(env, PROBLEM)
        alt_probe_prompt = env.seen_prompts[-1]
        self.assertIn("floats are not supported", alt_probe_prompt)
        self.assertIn("overflow is not handled", alt_probe_prompt)
        self.assertIn("inputs are always integers", alt_probe_prompt)

    def test_one_unparseable_draft_does_not_block_the_round(self):
        # Second draft never produces a valid READY_TO_CODE response even after its own
        # repair attempts -- the round must still proceed with the other two.
        env = _FakeEnv(
            llm_responses=(
                [_draft("A")]
                + ["garbage, no keyword at all"] * 4  # exhausts the per-agent repair cap
                + [_draft("C"), "DONE"]
            ),
        )
        result = LAASeR_GateV6().run(env, PROBLEM)
        self.assertIn("def add", result)

    def test_all_drafts_fail_returns_empty_without_raising(self):
        env = _FakeEnv(llm_responses=["garbage, no keyword at all"] * 20)
        result = LAASeR_GateV6().run(env, PROBLEM)
        self.assertEqual(result, "")

    def test_confirmed_divergence_triggers_a_second_round_of_three_drafts(self):
        env = _FakeEnv(
            llm_responses=[
                _draft("A"),
                _draft("B"),
                _draft("C"),
                ALT_BLOCK,
                _draft("A2"),
                _draft("B2"),
                _draft("C2"),
                "DONE",
            ],
            exec_code_responses=["DIVERGE_0_0=True A=-1 B=3"],
        )
        result = LAASeR_GateV6().run(env, PROBLEM)
        self.assertIn("def add", result)
        self.assertEqual(len(env.ask_human_calls), 1)
        self.assertIn("add(1, -2)", env.ask_human_calls[0])

    def test_llm_budget_exceeded_returns_empty_without_raising(self):
        env = _FakeEnv(llm_exception=LimitsExceededException("over budget"))
        result = LAASeR_GateV6().run(env, PROBLEM)
        self.assertEqual(result, "")

    def test_clarification_budget_exceeded_returns_candidate_seen_so_far(self):
        env = _FakeEnv(
            llm_responses=[_draft("A"), _draft("B"), _draft("C"), ALT_BLOCK],
            exec_code_responses=["DIVERGE_0_0=True A=-1 B=3"],
            ask_human_exception=TooManyQuestionException("too many questions"),
        )
        result = LAASeR_GateV6().run(env, PROBLEM)
        self.assertIn("def add", result)


if __name__ == "__main__":
    unittest.main()
