"""Regression tests for clarify/algorithms/laaser_pinpoint_dpll.py.

Offline, no network/Docker. The central property: without a contradiction certificate the
algorithm behaves exactly like LAASeR_Pinpoint (same question, same code path, one extra LLM
call for the formalization); the propositional layer can only change *which* question is asked,
never suppress one. The grounding script is executed for real in a subprocess (it uses
signal.alarm, so it needs its own main thread).
"""

from __future__ import annotations

import itertools
import random
import subprocess
import sys
import unittest

from clarify.algorithms.laaser_pinpoint_dpll import (
    LAASeR_PinpointDPLL,
    certify_contradiction,
    dpll_solve,
    minimal_unsat_core,
    parse_formalization,
    question_mentions,
)
from clarify.env import LimitsExceededException


def _models(clauses, n):
    out = []
    for bits in itertools.product([False, True], repeat=n):
        assignment = {v + 1: bits[v] for v in range(n)}
        if all(any(assignment[abs(lit)] == (lit > 0) for lit in c) for c in clauses):
            out.append(assignment)
    return out


def _random_cnf(rng, n, m):
    return [
        [rng.choice([1, -1]) * rng.randint(1, n) for _ in range(rng.randint(1, 3))]
        for _ in range(m)
    ]


class DPLLCoreTest(unittest.TestCase):
    def test_solve_agrees_with_brute_force(self):
        rng = random.Random(17)
        for _ in range(400):
            n, m = rng.randint(1, 7), rng.randint(0, 24)
            clauses = _random_cnf(rng, n, m)
            model = dpll_solve(clauses, n)
            self.assertEqual(model is None, not _models(clauses, n), clauses)
            if model is not None:
                for clause in clauses:
                    self.assertTrue(any(model[abs(lit)] == (lit > 0) for lit in clause))

    def test_minimal_unsat_core_is_unsat_and_minimal(self):
        rng = random.Random(23)
        checked = 0
        for _ in range(400):
            n = rng.randint(1, 5)
            groups = [_random_cnf(rng, n, rng.randint(1, 3)) for _ in range(rng.randint(1, 7))]
            core = minimal_unsat_core(groups, n)
            if core is None:
                self.assertTrue(_models([c for g in groups for c in g], n))
                continue
            checked += 1
            self.assertFalse(_models([c for i in core for c in groups[i]], n))
            for drop in core:
                self.assertTrue(_models([c for i in core if i != drop for c in groups[i]], n))
        self.assertGreater(checked, 50)


# -------------------------------------------------------------------------------------------------

MBPP_PROMPT = (
    "Write a function to find similar elements from two tuple lists, where the result must "
    "contain only elements that appear in exactly one of the two inputs."
)
MBPP = {"prompt": MBPP_PROMPT, "entry_point": "similar_elements"}

CONTRADICTION_FORMAL = """
**ATOM** common | A: the result holds elements present in both inputs | B: the result holds elements present in exactly one input
EVIDENCE "find similar elements from two tuple lists" => common=A
EVIDENCE "elements that appear in exactly one of the two inputs" => common=B
"""

SAME_STATEMENT_FORMAL = """
ATOM common | A: shared elements | B: elements in exactly one input
EVIDENCE "similar elements" => common=A
EVIDENCE "find similar elements from two tuple lists" => common=B
"""

INVENTED_QUOTE_FORMAL = """
ATOM common | A: shared elements | B: elements in exactly one input
EVIDENCE "find similar elements from two tuple lists" => common=A
EVIDENCE "the result is sorted in descending order" => common=B
"""

SIM_CODE = "```python\ndef similar_elements(a, b):\n    return tuple(set(a) & set(b))\n```"

AUDIT_ASK_UNRELATED = (
    'STEP 1 - DEFECTS\n- MISSING | "not stated" | reading A: tuple | reading B: list | IMPACT: HIGH\n'
    "DECISION: ASK\nQUESTION: Should the result be returned as a tuple or as a list?"
)
AUDIT_ASK_RELATED = (
    'DECISION: ASK\nQUESTION: The task says "exactly one of the two inputs" - should the result '
    "be the common elements or the symmetric difference?"
)
AUDIT_CODE = "DECISION: CODE\n" + SIM_CODE


class _FakeEnv:
    def __init__(self, llm_responses, answer="The common elements.", exec_mode="real", **kw):
        self.llm_responses = list(llm_responses)
        self.answer = answer
        self.exec_mode = exec_mode
        self.raise_at = kw.get("raise_at", {})
        self.prompts: list[str] = []
        self.questions: list[str] = []
        self.exec_calls = 0

    def llm(self, messages):
        content = messages if isinstance(messages, str) else messages[-1]["content"]
        self.prompts.append(content)
        if len(self.prompts) - 1 in self.raise_at:
            raise self.raise_at[len(self.prompts) - 1]
        return self.llm_responses.pop(0)

    def can_ask(self):
        return True

    def ask_human(self, query):
        self.questions.append(query)
        return self.answer

    def exec_code(self, script):
        self.exec_calls += 1
        if self.exec_mode == "raise":
            raise RuntimeError("docker unavailable")
        done = subprocess.run(
            [sys.executable, "-I", "-c", script], capture_output=True, text=True, timeout=60
        )
        return done.stdout + done.stderr


class PinpointParityTest(unittest.TestCase):
    """No certificate -> the exact Pinpoint behaviour."""

    def _assert_pinpoint_question(self, formal_response):
        env = _FakeEnv([AUDIT_ASK_UNRELATED, formal_response, SIM_CODE])
        result = LAASeR_PinpointDPLL().run(env, MBPP)
        self.assertIn("def similar_elements", result)
        self.assertEqual(env.questions, ["Should the result be returned as a tuple or as a list?"])
        self.assertEqual(len(env.prompts), 3)  # audit, formalize, code

    def test_nothing_open(self):
        self._assert_pinpoint_question("ATOM none")

    def test_garbage_formalization(self):
        self._assert_pinpoint_question("I am not sure what you mean.")

    def test_consistent_evidence(self):
        self._assert_pinpoint_question(
            'ATOM common | A: shared | B: exclusive\nEVIDENCE "similar elements" => common=A'
        )

    def test_overlapping_statements_are_not_a_certificate(self):
        self._assert_pinpoint_question(SAME_STATEMENT_FORMAL)

    def test_invented_quote_is_not_a_certificate(self):
        self._assert_pinpoint_question(INVENTED_QUOTE_FORMAL)

    def test_formalization_call_failure_falls_back(self):
        env = _FakeEnv(
            [AUDIT_ASK_UNRELATED, SIM_CODE], raise_at={1: LimitsExceededException("budget")}
        )
        LAASeR_PinpointDPLL().run(env, MBPP)
        self.assertEqual(env.questions, ["Should the result be returned as a tuple or as a list?"])

    def test_code_decision_without_certificate_codes_directly(self):
        env = _FakeEnv([AUDIT_CODE, "ATOM none"])
        result = LAASeR_PinpointDPLL().run(env, MBPP)
        self.assertIn("def similar_elements", result)
        self.assertEqual((env.questions, len(env.prompts)), ([], 2))


class CertificateTest(unittest.TestCase):
    def test_opt_in_replacement_swaps_an_unrelated_question(self):
        env = _FakeEnv([AUDIT_ASK_UNRELATED, CONTRADICTION_FORMAL, SIM_CODE])
        LAASeR_PinpointDPLL({"replace_question": True}).run(env, MBPP)
        self.assertEqual(len(env.questions), 1)
        question = env.questions[0]
        self.assertTrue(
            question.startswith(
                'The task says "find similar elements from two tuple lists" but also '
                '"elements that appear in exactly one of the two inputs".'
            ),
            question,
        )
        self.assertEqual(question.count("?"), 1)
        self.assertIn("Answer: The common elements.", env.prompts[-1])

    def test_question_already_about_the_contradiction_is_kept(self):
        env = _FakeEnv([AUDIT_ASK_RELATED, CONTRADICTION_FORMAL, SIM_CODE])
        LAASeR_PinpointDPLL({"replace_question": True}).run(env, MBPP)
        self.assertIn("symmetric difference", env.questions[0])

    def test_by_default_the_audits_own_question_is_kept(self):
        env = _FakeEnv([AUDIT_ASK_UNRELATED, CONTRADICTION_FORMAL, SIM_CODE])
        LAASeR_PinpointDPLL().run(env, MBPP)
        self.assertEqual(env.questions, ["Should the result be returned as a tuple or as a list?"])

    def test_code_decision_is_rescued_by_a_certificate(self):
        env = _FakeEnv([AUDIT_CODE, CONTRADICTION_FORMAL, SIM_CODE])
        result = LAASeR_PinpointDPLL().run(env, MBPP)
        self.assertIn("def similar_elements", result)
        self.assertEqual(len(env.questions), 1)
        self.assertIn("but also", env.questions[0])

    def test_example_grounding_certifies_text_vs_example(self):
        prompt = (
            "def truncate_number(number: float) -> float:\n"
            '    """ Return the decimal part of the number.\n'
            "    >>> truncate_number(3.5)\n"
            "    3\n"
            '    """\n'
        )
        problem = {"prompt": prompt, "entry_point": "truncate_number"}
        formal = (
            "ATOM part | A: the decimal part is returned | B: the integer part is returned\n"
            "CHECK part | A: abs(result - (number - int(number))) < 1e-9 | B: result == int(number)\n"
            'EVIDENCE "Return the decimal part of the number" => part=A\n'
        )
        code = "```python\ndef truncate_number(number):\n    return number % 1.0\n```"
        audit = "DECISION: CODE\n" + code  # the audit would code through the contradiction
        env = _FakeEnv([audit, formal, code], answer="The decimal part.")
        LAASeR_PinpointDPLL().run(env, problem)
        self.assertEqual(env.exec_calls, 1)
        self.assertEqual(
            env.questions[0],
            'The task says "Return the decimal part of the number" but also '
            '"truncate_number(3.5) == 3". Which is intended: the decimal part is returned, '
            "or the integer part is returned?",
        )

    def test_sandbox_failure_means_no_example_evidence(self):
        prompt = 'def f(x):\n    """ Return x + 1.\n    >>> f(1)\n    5\n    """\n'
        formal = (
            "ATOM inc | A: adds one | B: adds four\n"
            "CHECK inc | A: result == x + 1 | B: result == x + 4\n"
            'EVIDENCE "Return x + 1" => inc=A\n'
        )
        audit = "DECISION: CODE\n```python\ndef f(x):\n    return x + 1\n```"
        env = _FakeEnv([audit, formal], exec_mode="raise")
        result = LAASeR_PinpointDPLL().run(env, {"prompt": prompt, "entry_point": "f"})
        self.assertIn("return x + 1", result)
        self.assertEqual((env.exec_calls, env.questions), (1, []))  # no certificate, no question

    def test_stub_from_the_coder_goes_through_repair(self):
        # Mbpp/888 in smoke-70 r1: the coder answered with a function that only `return`s.
        stub = "```python\ndef similar_elements(pairs=[(5, 3), (2, 1)]):\n    return\n```"
        env = _FakeEnv([AUDIT_ASK_UNRELATED, "ATOM none", stub, SIM_CODE])
        result = LAASeR_PinpointDPLL().run(env, MBPP)
        self.assertIn("set(a) & set(b)", result)
        self.assertIn("does nothing", env.prompts[-1])

    def test_stub_shapes_are_detected_and_real_bodies_are_not(self):
        stubs = ["pass", "return", "return None", "...", '"""todo"""', "raise NotImplementedError"]
        for body in stubs:
            stub = f"```python\ndef similar_elements(a, b):\n    {body}\n```"
            env = _FakeEnv([AUDIT_ASK_UNRELATED, "ATOM none", stub, SIM_CODE])
            self.assertIn("set(a) & set(b)", LAASeR_PinpointDPLL().run(env, MBPP), body)
        for body in ["return [9, 9]", "return a"]:
            code = f"```python\ndef similar_elements(a, b):\n    {body}\n```"
            env = _FakeEnv([AUDIT_ASK_UNRELATED, "ATOM none", code])
            self.assertIn(body, LAASeR_PinpointDPLL().run(env, MBPP))
            self.assertEqual(len(env.prompts), 3)  # no repair call

    def test_atomic_question_flag(self):
        audit = "DECISION: ASK\nQUESTION: Tuple or list? Also, should duplicates be kept?"
        env = _FakeEnv([audit, "ATOM none", SIM_CODE])
        LAASeR_PinpointDPLL({"atomic_question": True}).run(env, MBPP)
        self.assertEqual(env.questions, ["Tuple or list?"])


class HelpersTest(unittest.TestCase):
    def test_parser_tolerates_markdown_and_numbering(self):
        response = (
            "1. **ATOM** `zero_side` | A: zero counts as negative | B: zero counts as positive\n"
            "- EVIDENCE: “not in the prompt” => zero_side=A\n"
        )
        formal = parse_formalization(response, MBPP_PROMPT, "similar_elements")
        self.assertEqual([a["name"] for a in formal["atoms"]], ["zero_side"])
        self.assertEqual(formal["evidence"], [])

    def test_certificate_needs_opposite_readings_of_one_atom(self):
        formal = {
            "atoms": [{"name": "a", "A": "x", "B": "y"}, {"name": "b", "A": "u", "B": "v"}],
            "evidence": [
                {"quote": "first statement", "clause": [("a", "A")], "source": "text"},
                {"quote": "second claim", "clause": [("b", "A")], "source": "text"},
            ],
        }
        self.assertIsNone(certify_contradiction(formal, []))

    def test_question_mentions(self):
        quotes = ("Return the decimal part of the number", "truncate_number(3.5) == 3")
        self.assertTrue(question_mentions("Decimal part or integer part?", quotes))
        self.assertFalse(question_mentions("What about negative inputs?", quotes))

    def test_question_mentions_real_misses_from_smoke70(self):
        # Both audit questions were replaced in smoke-70 r1 although they addressed the
        # contradiction: different word forms ("subtraction") and literals ("[9,9]").
        mbpp_888 = (
            "Should the function take the list [(5,3),(2,1)] as input and perform element-wise "
            "subtraction within each tuple (e.g. 5-3=2 and 2-1=1) and then return those "
            "results, or should it ignore the input and always return [9,9] regardless?"
        )
        quotes_888 = ("Write a function to subtract elements of [(5,3),(2,1)]", "but return [9,9].")
        self.assertTrue(question_mentions(mbpp_888, quotes_888))
        he_72 = (
            'The task says "it\'s unbalanced" with example will_it_fly([1, 2], 5) ➞ False, is '
            '"balanced" defined as the list q being symmetric (palindromic)?'
        )
        quotes_72 = ("will_it_fly([3], 5) == True", "will_it_fly([1, 2], 5) == False")
        self.assertTrue(question_mentions(he_72, quotes_72))


if __name__ == "__main__":
    unittest.main()
