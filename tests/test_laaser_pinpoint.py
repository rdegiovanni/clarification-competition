"""Regression tests for clarify/algorithms/laaser_pinpoint.py.

Offline, no network/Docker (same _FakeEnv pattern as tests/test_laaser_selfcheck.py). Pinpoint
runs one AUDIT call that either codes directly (`DECISION: CODE`, no question) or asks one
question about the highest-impact defect (`DECISION: ASK` + `QUESTION: ...`), then codes with
the answer treated as authoritative, followed by a bounded syntax/entry-point repair step.
"""

from __future__ import annotations

import unittest

from clarify.algorithms.laaser_pinpoint import LAASeR_Pinpoint
from clarify.env import LimitsExceededException, TooManyQuestionException

PROBLEM = {"prompt": "Write a function that adds two numbers.", "entry_point": "add"}

GOOD_CODE = "```python\ndef add(a, b):\n    return a + b\n```"
WRONG_NAME_CODE = "```python\ndef plus(a, b):\n    return a + b\n```"
BROKEN_CODE = "```python\ndef add(a, b)\n    return a + b\n```"

AUDIT_CODE = "- none\nDECISION: CODE\n" + GOOD_CODE
AUDIT_ASK = (
    '- VAGUE | "adds" | reading A: a + b | reading B: concatenation | IMPACT: HIGH\n'
    "DECISION: ASK\n"
    "QUESTION: Should add('1', '2') concatenate the strings, or convert them to numbers first?\n"
)


class _FakeEnv:
    """Minimal stand-in for ClarificationEnvironment exposing llm/ask_human/can_ask."""

    def __init__(
        self,
        llm_responses=None,
        llm_exception=None,
        ask_human_exception=None,
        can_ask=True,
        answer="Convert them to numbers first.",
    ):
        self._llm_responses = list(llm_responses or [])
        self._llm_exception = llm_exception
        self._ask_human_exception = ask_human_exception
        self._can_ask = can_ask
        self._answer = answer
        self.seen_prompts: list[str] = []
        self.ask_human_calls: list[str] = []

    def llm(self, messages):
        content = messages if isinstance(messages, str) else messages[-1]["content"]
        self.seen_prompts.append(content)
        if self._llm_exception is not None:
            raise self._llm_exception
        return self._llm_responses.pop(0)

    def can_ask(self):
        return self._can_ask

    def ask_human(self, query):
        self.ask_human_calls.append(query)
        if self._ask_human_exception is not None:
            raise self._ask_human_exception
        return self._answer


class LAASeRPinpointTest(unittest.TestCase):
    def test_code_decision_returns_audit_code_without_asking(self):
        env = _FakeEnv(llm_responses=[AUDIT_CODE])
        result = LAASeR_Pinpoint().run(env, PROBLEM)
        self.assertIn("def add(a, b)", result)
        self.assertEqual(env.ask_human_calls, [])
        self.assertEqual(len(env.seen_prompts), 1)

    def test_ask_decision_asks_once_and_codes_with_the_answer(self):
        env = _FakeEnv(llm_responses=[AUDIT_ASK, GOOD_CODE])
        result = LAASeR_Pinpoint().run(env, PROBLEM)
        self.assertIn("def add(a, b)", result)
        self.assertEqual(
            env.ask_human_calls,
            ["Should add('1', '2') concatenate the strings, or convert them to numbers first?"],
        )
        code_prompt = env.seen_prompts[1]
        self.assertIn("Convert them to numbers first.", code_prompt)
        self.assertIn("concatenate the strings", code_prompt)

    def test_question_without_decision_line_is_still_asked(self):
        audit = "QUESTION: **Should the result be an int or a float?**\n"
        env = _FakeEnv(llm_responses=[audit, GOOD_CODE])
        LAASeR_Pinpoint().run(env, PROBLEM)
        self.assertEqual(env.ask_human_calls, ["Should the result be an int or a float?"])

    def test_markdown_decision_line_is_parsed(self):
        audit = "**DECISION**: ASK\nQUESTION: Should negative inputs be rejected or summed?"
        env = _FakeEnv(llm_responses=[audit, GOOD_CODE])
        LAASeR_Pinpoint().run(env, PROBLEM)
        self.assertEqual(len(env.ask_human_calls), 1)

    def test_no_ask_when_budget_is_exhausted(self):
        env = _FakeEnv(llm_responses=[AUDIT_ASK, GOOD_CODE], can_ask=False)
        result = LAASeR_Pinpoint().run(env, PROBLEM)
        self.assertIn("def add(a, b)", result)
        self.assertEqual(env.ask_human_calls, [])
        self.assertNotIn("Question:", env.seen_prompts[1])

    def test_too_many_questions_still_produces_code(self):
        env = _FakeEnv(
            llm_responses=[AUDIT_ASK, GOOD_CODE],
            ask_human_exception=TooManyQuestionException("limit"),
        )
        result = LAASeR_Pinpoint().run(env, PROBLEM)
        self.assertIn("def add(a, b)", result)
        self.assertNotIn("Question:", env.seen_prompts[1])

    def test_limits_exceeded_on_first_call_returns_empty_without_crashing(self):
        env = _FakeEnv(llm_exception=LimitsExceededException("budget"))
        self.assertEqual(LAASeR_Pinpoint().run(env, PROBLEM), "")

    def test_wrong_entry_point_is_repaired(self):
        env = _FakeEnv(llm_responses=[AUDIT_ASK, WRONG_NAME_CODE, GOOD_CODE])
        result = LAASeR_Pinpoint().run(env, PROBLEM)
        self.assertIn("def add(a, b)", result)
        self.assertIn("named exactly `add`", env.seen_prompts[2])

    def test_unrepairable_entry_point_falls_back_to_alias(self):
        env = _FakeEnv(llm_responses=[AUDIT_ASK, WRONG_NAME_CODE, WRONG_NAME_CODE, WRONG_NAME_CODE])
        result = LAASeR_Pinpoint().run(env, PROBLEM)
        self.assertIn("def plus(a, b)", result)
        self.assertTrue(result.rstrip().endswith("add = plus"))
        namespace: dict = {}
        exec(result, namespace)  # noqa: S102 -- trusted, test-local code
        self.assertEqual(namespace["add"](2, 3), 5)

    def test_syntax_error_in_code_decision_is_repaired(self):
        env = _FakeEnv(llm_responses=["DECISION: CODE\n" + BROKEN_CODE, GOOD_CODE])
        result = LAASeR_Pinpoint().run(env, PROBLEM)
        self.assertEqual(result.strip(), "def add(a, b):\n    return a + b")
        self.assertIn("not valid Python", env.seen_prompts[1])

    def test_limits_exceeded_during_repair_keeps_best_candidate(self):
        class _BudgetEnv(_FakeEnv):
            def llm(self, messages):
                if len(self.seen_prompts) == 2:
                    raise LimitsExceededException("budget")
                return super().llm(messages)

        env = _BudgetEnv(llm_responses=[AUDIT_ASK, WRONG_NAME_CODE])
        result = LAASeR_Pinpoint().run(env, PROBLEM)
        self.assertIn("def plus(a, b)", result)

    def test_prompt_braces_are_not_treated_as_placeholders(self):
        problem = {
            "prompt": "Return {rules} and {entry_point} literally as a dict key.",
            "entry_point": "add",
        }
        env = _FakeEnv(llm_responses=[AUDIT_CODE])
        LAASeR_Pinpoint().run(env, problem)
        self.assertIn("Return {rules} and {entry_point} literally", env.seen_prompts[0])


if __name__ == "__main__":
    unittest.main()
