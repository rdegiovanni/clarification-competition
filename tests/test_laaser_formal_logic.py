"""Regression tests for clarify/algorithms/laaser_formal_logic.py.

Same mechanism and _FakeEnv pattern as tests/test_laaser_formal_verified.py (unchanged: SAT check,
divergence gate, repair/finalize) -- only the FORMALIZE prompt wording changed, so most of this
suite is carried over verbatim. New tests cover the two wording changes specifically: (1) a prompt
content check that the mandatory signature-first instruction and the logical/Python-predicate
example are actually in the prompt sent to the model, and (2) a real-exec test proving a genuine
arity mismatch (1-arg vs 2-arg candidates) produces a TypeError-based divergence through the
existing probe script, with no changes needed to it.
"""

from __future__ import annotations

import contextlib
import io
import unittest

from clarify.algorithms.laaser_formal_logic import LAASeR_FormalLogic
from clarify.env import LimitsExceededException, TooManyQuestionException

PROBLEM = {"prompt": "Write a function that scales a number.", "entry_point": "scale"}

GOOD_CODE = "```python\ndef scale(x):\n    return x * 2\n```"
WRONG_NAME_CODE = "```python\ndef mul(x):\n    return x * 2\n```"
BROKEN_CODE = "```python\ndef scale(x)\n    return x * 2\n```"

NO_DEFECTS_CODE = 'FORMALIZATION: {"defects": [], "clauses": []}\nDECISION: CODE\n' + GOOD_CODE

ONE_ATOM_CONTRADICTION = (
    'FORMALIZATION: {"defects": [{"atom": "scale_mode", '
    '"phrase": "doubles the input but also triples the input", '
    '"reading_true": "result == x * 2", "reading_false": "result == x * 3", '
    '"baseline": True}], "clauses": [["scale_mode"], ["-scale_mode"]]}\n'
    "DECISION: CODE\n" + GOOD_CODE
)

ONE_ATOM_NO_CLAUSE = (
    'FORMALIZATION: {"defects": [{"atom": "scale_mode", "phrase": "not stated", '
    '"reading_true": "result == x * 2", "reading_false": "result == x * 3", '
    '"baseline": True}], "clauses": []}\n'
    "DECISION: CODE\n" + GOOD_CODE
)

ONE_ATOM_DETERMINED = (
    'FORMALIZATION: {"defects": [{"atom": "scale_mode", "phrase": "always doubles", '
    '"reading_true": "result == x * 2", "reading_false": "result == x * 3", '
    '"baseline": True}], "clauses": [["scale_mode"]]}\n'
    "DECISION: CODE\n" + GOOD_CODE
)

# A mandatory signature atom listed first, exactly as the new STEP 1 wording requires.
SIGNATURE_ATOM_FIRST = (
    'FORMALIZATION: {"defects": [{"atom": "takes_only_x", "phrase": "not stated", '
    '"reading_true": "scale(x) takes exactly one parameter x", '
    '"reading_false": "scale(x, factor) also takes a second parameter factor", '
    '"baseline": True}], "clauses": []}\n'
    "DECISION: CODE\n" + GOOD_CODE
)

# Two atoms, listed A-then-B; B's own clause requires it True but B's baseline is False, so the
# violated clause is about B, not the first-listed A -- the UNSAT atom-attribution fix must blame B.
TWO_ATOM_UNSAT_SECOND = (
    'FORMALIZATION: {"defects": ['
    '{"atom": "atom_a", "phrase": "not stated", "reading_true": "a is true", '
    '"reading_false": "a is false", "baseline": True}, '
    '{"atom": "atom_b", "phrase": "atom b phrase", "reading_true": "b is true", '
    '"reading_false": "b is false", "baseline": False}'
    '], "clauses": [["atom_b"]]}\n'
    "DECISION: CODE\n" + GOOD_CODE
)

DIVERGING_PROBE_RESPONSE = (
    "CANDIDATE_A:\n```python\ndef scale(x):\n    return x * 2\n```\n"
    "CANDIDATE_B:\n```python\ndef scale(x):\n    return x * 3\n```\n"
    "INPUTS: [(2,), (5,)]\n"
)

NONDIVERGING_PROBE_RESPONSE = (
    "CANDIDATE_A:\n```python\ndef scale(x):\n    return x * 2\n```\n"
    "CANDIDATE_B:\n```python\ndef scale(x):\n    return x * 2\n```\n"
    "INPUTS: [(2,), (5,)]\n"
)

# One-arg vs two-arg candidates, probed with 2-element input tuples -- calling the one-arg
# candidate with 2 arguments must raise a TypeError inside the probe script, which already
# counts as a divergence with no changes to that script.
ARITY_MISMATCH_PROBE_RESPONSE = (
    "CANDIDATE_A:\n```python\ndef scale(x):\n    return x * 2\n```\n"
    "CANDIDATE_B:\n```python\ndef scale(x, factor):\n    return x * factor\n```\n"
    "INPUTS: [(2, 3), (5, 4)]\n"
)

GARBAGE_PROBE_RESPONSE = "I could not come up with two candidates for this task."


class _FakeEnv:
    """Minimal stand-in for ClarificationEnvironment exposing llm/ask_human/can_ask/exec_code."""

    def __init__(
        self,
        llm_responses=None,
        llm_exception=None,
        ask_human_exception=None,
        can_ask=True,
        answer="x * 2",
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


class LAASeRFormalLogicTest(unittest.TestCase):
    def test_divergence_probe_prompt_requires_matching_fixed_arity(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_NO_CLAUSE, DIVERGING_PROBE_RESPONSE, GOOD_CODE],
            exec_code_responses=[
                "SAT_RESULT=AMBIGUOUS atoms=['scale_mode']",
                "DIVERGE_0=True\nDIVERGE_1=True",
            ],
        )
        LAASeR_FormalLogic().run(env, PROBLEM)
        probe_prompt = env.seen_prompts[1]
        self.assertIn("required, fixed-count signature", probe_prompt)
        self.assertIn("never `*args`", probe_prompt)
        self.assertIn("sized for EACH candidate's own argument", probe_prompt)

    def test_prompt_treats_signature_as_an_ordinary_equal_footing_defect(self):
        env = _FakeEnv(llm_responses=[NO_DEFECTS_CODE])
        LAASeR_FormalLogic().run(env, PROBLEM)
        prompt = env.seen_prompts[0]
        self.assertIn("whether the exact number, order and type", prompt)
        self.assertIn("on equal footing with every other", prompt)
        self.assertNotIn("listed first, before any other defect", prompt)
        self.assertIn("Never write it as literal Python code", prompt)
        self.assertIn("rather than a vague paraphrase", prompt)

    def test_zero_defects_codes_directly_without_asking_or_exec(self):
        env = _FakeEnv(llm_responses=[NO_DEFECTS_CODE])
        result = LAASeR_FormalLogic().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.ask_human_calls, [])
        self.assertEqual(env.exec_code_calls, 0)

    def test_unsat_asks_immediately_without_a_divergence_probe(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_CONTRADICTION, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=UNSAT"],
        )
        result = LAASeR_FormalLogic().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.exec_code_calls, 1)
        self.assertEqual(len(env.ask_human_calls), 1)

    def test_unsat_blames_the_atom_in_the_violated_clause_not_the_first_listed(self):
        env = _FakeEnv(
            llm_responses=[TWO_ATOM_UNSAT_SECOND, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=UNSAT atoms=['atom_b']"],
        )
        LAASeR_FormalLogic().run(env, PROBLEM)
        self.assertEqual(len(env.ask_human_calls), 1)
        self.assertIn("b is true", env.ask_human_calls[0])
        self.assertNotIn("a is true", env.ask_human_calls[0])

    def test_real_unsat_script_blames_the_violated_clauses_atom(self):
        # End-to-end: the real SAT_SCRIPT_TEMPLATE must itself report atom_b, not atom_a, since
        # atom_b's own clause (requiring it True) is the one its baseline (False) violates.
        env = _FakeEnv(llm_responses=[TWO_ATOM_UNSAT_SECOND, GOOD_CODE], real_exec_code=True)
        LAASeR_FormalLogic().run(env, PROBLEM)
        self.assertEqual(len(env.ask_human_calls), 1)
        self.assertIn("b is true", env.ask_human_calls[0])
        self.assertNotIn("a is true", env.ask_human_calls[0])

    def test_determined_codes_without_asking_or_probing(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_DETERMINED, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=DETERMINED"],
        )
        result = LAASeR_FormalLogic().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.ask_human_calls, [])

    def test_ambiguous_with_real_divergence_asks(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_NO_CLAUSE, DIVERGING_PROBE_RESPONSE, GOOD_CODE],
            exec_code_responses=[
                "SAT_RESULT=AMBIGUOUS atoms=['scale_mode']",
                "DIVERGE_0=True\nDIVERGE_1=True",
            ],
        )
        result = LAASeR_FormalLogic().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(len(env.ask_human_calls), 1)

    def test_ambiguous_with_no_divergence_skips_the_question(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_NO_CLAUSE, NONDIVERGING_PROBE_RESPONSE, GOOD_CODE],
            exec_code_responses=[
                "SAT_RESULT=AMBIGUOUS atoms=['scale_mode']",
                "DIVERGE_0=False\nDIVERGE_1=False",
            ],
        )
        result = LAASeR_FormalLogic().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.ask_human_calls, [])

    def test_ambiguous_with_unparseable_probe_falls_back_to_asking(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_NO_CLAUSE, GARBAGE_PROBE_RESPONSE, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=AMBIGUOUS atoms=['scale_mode']"],
        )
        result = LAASeR_FormalLogic().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(len(env.ask_human_calls), 1)

    def test_mandatory_signature_atom_asks_when_ambiguous(self):
        env = _FakeEnv(
            llm_responses=[SIGNATURE_ATOM_FIRST, ARITY_MISMATCH_PROBE_RESPONSE, GOOD_CODE],
            exec_code_responses=[
                "SAT_RESULT=AMBIGUOUS atoms=['takes_only_x']",
                "DIVERGE_0=True\nDIVERGE_1=True",
            ],
        )
        result = LAASeR_FormalLogic().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(len(env.ask_human_calls), 1)
        self.assertIn("takes exactly one parameter", env.ask_human_calls[0])

    def test_real_arity_mismatch_probe_detects_divergence_via_typeerror(self):
        # End-to-end through the public API: candidate_a(x) called with a 2-element input tuple
        # must TypeError inside the real probe script, counted as a confirmed divergence, with no
        # changes to laaser_formal_verified.py's probe-script logic.
        env = _FakeEnv(
            llm_responses=[SIGNATURE_ATOM_FIRST, ARITY_MISMATCH_PROBE_RESPONSE, GOOD_CODE],
            real_exec_code=True,
        )
        LAASeR_FormalLogic().run(env, PROBLEM)
        self.assertEqual(env.exec_code_calls, 2)
        self.assertEqual(len(env.ask_human_calls), 1)

    def test_no_ask_when_budget_is_exhausted(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_CONTRADICTION, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=UNSAT"],
            can_ask=False,
        )
        result = LAASeR_FormalLogic().run(env, PROBLEM)
        self.assertIn("def scale", result)
        self.assertEqual(env.ask_human_calls, [])

    def test_too_many_questions_still_produces_code(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_CONTRADICTION, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=UNSAT"],
            ask_human_exception=TooManyQuestionException("limit"),
        )
        result = LAASeR_FormalLogic().run(env, PROBLEM)
        self.assertIn("def scale", result)

    def test_limits_exceeded_on_first_call_returns_empty_without_crashing(self):
        env = _FakeEnv(llm_exception=LimitsExceededException("budget"))
        self.assertEqual(LAASeR_FormalLogic().run(env, PROBLEM), "")

    def test_wrong_entry_point_is_repaired(self):
        env = _FakeEnv(
            llm_responses=[ONE_ATOM_CONTRADICTION, WRONG_NAME_CODE, GOOD_CODE],
            exec_code_responses=["SAT_RESULT=UNSAT"],
        )
        result = LAASeR_FormalLogic().run(env, PROBLEM)
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
        result = LAASeR_FormalLogic().run(env, PROBLEM)
        self.assertIn("def mul(x)", result)
        self.assertTrue(result.rstrip().endswith("scale = mul"))
        namespace: dict = {}
        exec(result, namespace)  # noqa: S102 -- trusted, test-local code
        self.assertEqual(namespace["scale"](3), 6)

    def test_syntax_error_in_code_decision_is_repaired(self):
        env = _FakeEnv(llm_responses=["DECISION: CODE\n" + BROKEN_CODE, GOOD_CODE])
        result = LAASeR_FormalLogic().run(env, PROBLEM)
        self.assertEqual(result.strip(), "def scale(x):\n    return x * 2")
        self.assertIn("not valid Python", env.seen_prompts[1])


if __name__ == "__main__":
    unittest.main()
