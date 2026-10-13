"""Regression tests for clarify/algorithms/laaser_formal.py.

Offline, no network/Docker (same _FakeEnv pattern as tests/test_laaser_selfcheck.py, extended with
`can_ask`). Most tests feed `exec_code` a canned `SAT_RESULT=...` line to isolate the ASK/CODE
decision logic from the brute-force script itself; a few use `real_exec_code=True` so `exec_code`
actually executes the generated script via Python's own `exec()`, to verify the brute-force SAT
checker is itself correct end-to-end through the public `run()` API (no private imports, same
convention as every other test file in this suite).
"""

from __future__ import annotations

import contextlib
import io
import unittest

from clarify.algorithms.laaser_formal import LAASeR_Formal
from clarify.env import LimitsExceededException, TooManyQuestionException

PROBLEM = {"prompt": "Write a function that scales a number.", "entry_point": "scale"}

GOOD_CODE = "```python\ndef scale(x):\n    return x * 2\n```"
WRONG_NAME_CODE = "```python\ndef mul(x):\n    return x * 2\n```"
BROKEN_CODE = "```python\ndef scale(x)\n    return x * 2\n```"

NO_DEFECTS_CODE = 'FORMALIZATION: {"defects": [], "clauses": []}\nDECISION: CODE\n' + GOOD_CODE
NO_DEFECTS_ASK_FALLBACK = (
    'FORMALIZATION: {"defects": [], "clauses": []}\n'
    "DECISION: ASK\nQUESTION: Should scaling double or triple the input?\n"
)
UNREADABLE_FORMALIZATION = (
    "FORMALIZATION: not even close to a dict\n"
    "DECISION: ASK\nQUESTION: Should scaling double or triple the input?\n"
)

ONE_ATOM_CONTRADICTION = (
    'FORMALIZATION: {"defects": [{"atom": "scale_mode", '
    '"phrase": "doubles the input but also triples the input", '
    '"reading_true": "it doubles the input", "reading_false": "it triples the input", '
    '"baseline": True}], "clauses": [["scale_mode"], ["-scale_mode"]]}\n'
    "DECISION: CODE\n" + GOOD_CODE
)

# Real observed model behavior: told to write "a dict literal", some responses skip the literal
# "FORMALIZATION:" marker word entirely and stop right after the dict, with no STEP 2 line either.
# This must still parse and reach the SAT check, not fall through to an empty fallback.
MARKERLESS_CONTRADICTION = (
    '{"defects": [{"atom": "scale_mode", '
    '"phrase": "doubles the input but also triples the input", '
    '"reading_true": "it doubles the input", "reading_false": "it triples the input", '
    '"baseline": True}], "clauses": [["scale_mode"], ["-scale_mode"]]}'
)

ONE_ATOM_BASELINE_MISMATCH = (
    'FORMALIZATION: {"defects": [{"atom": "scale_mode", "phrase": "always doubles", '
    '"reading_true": "it doubles the input", "reading_false": "it triples the input", '
    '"baseline": False}], "clauses": [["scale_mode"]]}\n'
    "DECISION: CODE\n" + GOOD_CODE
)

TWO_ATOMS_NO_CLAUSES = (
    'FORMALIZATION: {"defects": ['
    '{"atom": "scale_mode", "phrase": "not stated", "reading_true": "it doubles", '
    '"reading_false": "it triples", "baseline": False}, '
    '{"atom": "rounding", "phrase": "not stated", "reading_true": "rounds up", '
    '"reading_false": "rounds down", "baseline": False}'
    '], "clauses": []}\n'
    "DECISION: CODE\n" + GOOD_CODE
)

ONE_ATOM_DETERMINED = (
    'FORMALIZATION: {"defects": [{"atom": "scale_mode", "phrase": "always doubles", '
    '"reading_true": "it doubles the input", "reading_false": "it triples the input", '
    '"baseline": True}], "clauses": [["scale_mode"]]}\n'
    "DECISION: CODE\n" + GOOD_CODE
)

TOO_MANY_ATOMS = (
    'FORMALIZATION: {"defects": ['
    + ", ".join(
        f'{{"atom": "a{i}", "phrase": "not stated", "reading_true": "x", '
        f'"reading_false": "y", "baseline": True}}'
        for i in range(17)
    )
    + '], "clauses": []}\n'
    "DECISION: ASK\nQUESTION: Should scaling double or triple the input?\n"
)


class _FakeEnv:
    """Minimal stand-in for ClarificationEnvironment exposing llm/ask_human/can_ask/exec_code."""

    def __init__(
        self,
        llm_responses=None,
        llm_exception=None,
        ask_human_exception=None,
        can_ask=True,
        answer="It doubles the input.",
        exec_code_responses=None,
        real_exec_code=False,
    ):
        self._llm_responses = list(llm_responses or [])
        self._llm_exception = llm_exception
        self._ask_human_exception = ask_human_exception
        self._can_ask = can_ask
        self._answer = answer
        self._exec_code_responses = list(exec_code_responses or [])
        self._real_exec_code = real_exec_code
        self.seen_prompts: list[str] = []
        self.ask_human_calls: list[str] = []
        self.exec_code_calls = 0

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

    def exec_code(self, script):
        self.exec_code_calls += 1
        if self._real_exec_code:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                exec(script, {})  # noqa: S102 -- trusted, test-local script
            return buf.getvalue()
        return self._exec_code_responses.pop(0)


class LAASeRFormalTest(unittest.TestCase):
    def test_zero_defects_codes_directly_without_asking_or_exec(self):
        env = _FakeEnv(llm_responses=[NO_DEFECTS_CODE])
        result = LAASeR_Formal().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.ask_human_calls, [])
        self.assertEqual(env.exec_code_calls, 0)
        self.assertEqual(len(env.seen_prompts), 1)

    def test_zero_defects_but_fallback_decision_is_ask(self):
        env = _FakeEnv(llm_responses=[NO_DEFECTS_ASK_FALLBACK, GOOD_CODE])
        result = LAASeR_Formal().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.exec_code_calls, 0)
        self.assertEqual(env.ask_human_calls, ["Should scaling double or triple the input?"])

    def test_unreadable_formalization_falls_back_to_decision_lines(self):
        env = _FakeEnv(llm_responses=[UNREADABLE_FORMALIZATION, GOOD_CODE])
        result = LAASeR_Formal().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.exec_code_calls, 0)
        self.assertEqual(len(env.ask_human_calls), 1)

    def test_too_many_atoms_skips_sat_check_and_falls_back(self):
        env = _FakeEnv(llm_responses=[TOO_MANY_ATOMS, GOOD_CODE])
        result = LAASeR_Formal().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.exec_code_calls, 0)
        self.assertEqual(len(env.ask_human_calls), 1)

    def test_unsat_contradiction_asks_about_the_contradicting_atom(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_CONTRADICTION, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=UNSAT"],
        )
        result = LAASeR_Formal().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.exec_code_calls, 1)
        self.assertEqual(len(env.ask_human_calls), 1)
        question = env.ask_human_calls[0]
        self.assertIn("doubles the input but also triples the input", question)
        self.assertIn("it doubles the input", question)
        self.assertIn("it triples the input", question)
        code_prompt = env.seen_prompts[1]
        self.assertIn("It doubles the input.", code_prompt)

    def test_markerless_formalization_still_parses_and_reaches_sat_check(self):
        # Regression: a response with no "FORMALIZATION:" marker and no STEP 2 line at all (the
        # model stopped right after the dict) must still be read -- it must not fall through to
        # the empty-fallback path, which previously burned a wasted repair round-trip per task.
        env = _FakeEnv(
            llm_responses=[MARKERLESS_CONTRADICTION, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=UNSAT"],
        )
        result = LAASeR_Formal().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.exec_code_calls, 1)
        self.assertEqual(len(env.ask_human_calls), 1)
        self.assertEqual(len(env.seen_prompts), 2)  # no wasted repair call

    def test_unsat_baseline_mismatch_also_asks(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_BASELINE_MISMATCH, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=UNSAT"],
        )
        result = LAASeR_Formal().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(len(env.ask_human_calls), 1)

    def test_ambiguous_asks_about_the_first_free_atom(self):
        env = _FakeEnv(
            llm_responses=[TWO_ATOMS_NO_CLAUSES, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=AMBIGUOUS atoms=['scale_mode', 'rounding']"],
        )
        result = LAASeR_Formal().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(len(env.ask_human_calls), 1)
        self.assertIn("it doubles", env.ask_human_calls[0])
        self.assertNotIn("rounds up", env.ask_human_calls[0])

    def test_determined_codes_without_asking_using_baseline_facts(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_DETERMINED, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=DETERMINED"],
        )
        result = LAASeR_Formal().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.exec_code_calls, 1)
        self.assertEqual(env.ask_human_calls, [])
        code_prompt = env.seen_prompts[1]
        self.assertIn("it doubles the input", code_prompt)

    def test_unparseable_sat_output_falls_back_to_decision_lines(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_DETERMINED, GOOD_CODE],
            exec_code_responses=["Traceback: something crashed\n"],
        )
        result = LAASeR_Formal().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.exec_code_calls, 1)
        self.assertEqual(env.ask_human_calls, [])

    def test_no_ask_when_budget_is_exhausted(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_CONTRADICTION, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=UNSAT"],
            can_ask=False,
        )
        result = LAASeR_Formal().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.ask_human_calls, [])

    def test_too_many_questions_still_produces_code(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_CONTRADICTION, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=UNSAT"],
            ask_human_exception=TooManyQuestionException("limit"),
        )
        result = LAASeR_Formal().run(env, PROBLEM)
        self.assertIn("def scale", result)

    def test_limits_exceeded_on_first_call_returns_empty_without_crashing(self):
        env = _FakeEnv(llm_exception=LimitsExceededException("budget"))
        self.assertEqual(LAASeR_Formal().run(env, PROBLEM), "")

    def test_wrong_entry_point_is_repaired(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_CONTRADICTION, WRONG_NAME_CODE, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=UNSAT"],
        )
        result = LAASeR_Formal().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertIn("named exactly `scale`", env.seen_prompts[2])

    def test_unrepairable_entry_point_falls_back_to_alias(self):
        env = _FakeEnv(
            llm_responses=[
                ONE_ATOM_CONTRADICTION,
                WRONG_NAME_CODE,
                WRONG_NAME_CODE,
                WRONG_NAME_CODE,
            ],
            exec_code_responses=["SAT_RESULT=UNSAT"],
        )
        result = LAASeR_Formal().run(env, PROBLEM)
        self.assertIn("def mul(x)", result)
        self.assertTrue(result.rstrip().endswith("scale = mul"))
        namespace: dict = {}
        exec(result, namespace)  # noqa: S102 -- trusted, test-local code
        self.assertEqual(namespace["scale"](3), 6)

    def test_syntax_error_in_code_decision_is_repaired(self):
        env = _FakeEnv(llm_responses=["DECISION: CODE\n" + BROKEN_CODE, GOOD_CODE])
        result = LAASeR_Formal().run(env, PROBLEM)
        self.assertEqual(result.strip(), "def scale(x):\n    return x * 2")
        self.assertIn("not valid Python", env.seen_prompts[1])

    # -- Real execution of the generated brute-force SAT script, through the public API --

    def test_real_sat_script_detects_contradiction(self):
        env = _FakeEnv(llm_responses=[ONE_ATOM_CONTRADICTION, GOOD_CODE], real_exec_code=True)
        LAASeR_Formal().run(env, PROBLEM)
        self.assertEqual(env.exec_code_calls, 1)
        self.assertEqual(len(env.ask_human_calls), 1)

    def test_real_sat_script_detects_ambiguity(self):
        env = _FakeEnv(llm_responses=[TWO_ATOMS_NO_CLAUSES, GOOD_CODE], real_exec_code=True)
        LAASeR_Formal().run(env, PROBLEM)
        self.assertEqual(len(env.ask_human_calls), 1)

    def test_real_sat_script_detects_determined(self):
        env = _FakeEnv(llm_responses=[ONE_ATOM_DETERMINED, GOOD_CODE], real_exec_code=True)
        LAASeR_Formal().run(env, PROBLEM)
        self.assertEqual(env.ask_human_calls, [])


if __name__ == "__main__":
    unittest.main()
