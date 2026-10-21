"""Regression tests for clarify/algorithms/laaser_pinpoint_smt.py.

Offline, no network/Docker. z3 is an optional dependency (requested from the organizers): the
tests that need the solver are skipped when `z3-solver` is not installed, and one test checks
that the algorithm still runs -- as Pinpoint plus the mechanical type-clash check -- without it.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import unittest

from clarify.algorithms import laaser_pinpoint, laaser_pinpoint_smt
from clarify.algorithms.laaser_pinpoint_smt import (
    AUDIT_CHECKLIST_TEMPLATE,
    AUDIT_TEMPLATE,
    LAASeR_PinpointSMT,
    analyse_readings,
    audit_defects,
    checklist_block,
    choose_ambiguity,
    definition_signature,
    extract_examples,
    hint_sort,
    infer_signature,
    parse_probe_calls,
    parse_readings,
    parse_results,
    parse_smt_statements,
    question_mentions,
    same_shape,
    same_value,
    smt_certificate,
    smt_value,
    tolerate_extra_args,
    type_clash,
    unify,
    usable_answer,
    value_sort,
)
from clarify.env import LimitsExceededException

HAS_Z3 = laaser_pinpoint_smt.z3 is not None


def _algo(**config):
    """The algorithm with Pinpoint's audit and without the execution check and the
    extra-argument edit, unless a test turns them on."""
    return LAASeR_PinpointSMT(
        {"verify": False, "tolerate_extra_args": False, "checklist": False, **config}
    )


TRUNC_PROMPT = (
    "def truncate_number(number: float) -> float:\n"
    '    """ Return the decimal part of the number.\n'
    "    >>> truncate_number(3.5)\n"
    "    3\n"
    '    """\n'
)
TRUNC = {"prompt": TRUNC_PROMPT, "entry_point": "truncate_number"}
TRUNC_SMT = (
    'STATEMENT "Return the decimal part of the number."\n'
    "ASSERT (forall ((x Real)) (= (f x) (- x (to_real (to_int x)))))\n"
)
TRUNC_CODE = "```python\ndef truncate_number(number):\n    return number % 1.0\n```"

SUM_PROMPT = (
    "from typing import List\n"
    "def total(xs: List[int]) -> int:\n"
    '    """ Return the sum of the list.\n'
    "    >>> total([1, 2, 3])\n"
    "    7\n"
    '    """\n'
)
SUM_SMT = (
    "DEFINE (define-fun-rec s ((xs (Seq Int))) Int (ite (= (seq.len xs) 0) 0 (+ (seq.nth xs 0) "
    "(s (seq.extract xs 1 (- (seq.len xs) 1))))))\n"
    'STATEMENT "Return the sum of the list."\n'
    "ASSERT (forall ((xs (Seq Int))) (= (f xs) (s xs)))\n"
)

MBPP = {"prompt": "Write a function to sum the items of an array.", "entry_point": "sum_arr"}

COUNT = {
    "prompt": "Write a function to count the elements of a list that are greater than k.",
    "entry_point": "count_greater",
}
COUNT_AUDIT = (
    "STEP 1 - DEFECTS\n"
    '- VAGUE | "greater than" | reading A: strictly greater than k | reading B: greater than or '
    "equal to k | IMPACT: HIGH\n"
    "STEP 2 - DECISION\nDECISION: ASK\nQUESTION: Should elements equal to k be counted?"
)
COUNT_READINGS = (
    'AMBIGUITY "greater than"\n'
    "READING A: Count only elements strictly greater than k.\n"
    "DEFINE A (define-fun-rec fa ((xs (Seq Int)) (k Int)) Int (ite (= (seq.len xs) 0) 0 "
    "(+ (ite (> (seq.nth xs 0) k) 1 0) (fa (seq.extract xs 1 (- (seq.len xs) 1)) k))))\n"
    "READING B: Count elements greater than or equal to k.\n"
    "DEFINE B (define-fun-rec fb ((xs (Seq Int)) (k Int)) Int (ite (= (seq.len xs) 0) 0 "
    "(+ (ite (>= (seq.nth xs 0) k) 1 0) (fb (seq.extract xs 1 (- (seq.len xs) 1)) k))))\n"
)
COUNT_CODE = "```python\ndef count_greater(xs, k):\n    return sum(1 for x in xs if x > k)\n```"
POSITIVE = {
    "prompt": "Write a function to sum the positive numbers of a list.",
    "entry_point": "sum_positive",
}
POSITIVE_AUDIT = (
    '- VAGUE | "positive numbers" | reading A: greater than 0 | reading B: at least 0 | '
    "IMPACT: HIGH\nDECISION: ASK\nQUESTION: Should zero count as a positive number?"
)
POSITIVE_READINGS = (
    'AMBIGUITY "positive numbers"\n'
    "READING A: Sum the numbers greater than 0.\n"
    "DEFINE A (define-fun-rec fa ((xs (Seq Int))) Int (ite (= (seq.len xs) 0) 0 (+ (ite (> "
    "(seq.nth xs 0) 0) (seq.nth xs 0) 0) (fa (seq.extract xs 1 (- (seq.len xs) 1))))))\n"
    "READING B: Sum the numbers greater than or equal to 0.\n"
    "DEFINE B (define-fun-rec fb ((xs (Seq Int))) Int (ite (= (seq.len xs) 0) 0 (+ (ite (>= "
    "(seq.nth xs 0) 0) (seq.nth xs 0) 0) (fb (seq.extract xs 1 (- (seq.len xs) 1))))))\n"
)
POSITIVE_CODE = "```python\ndef sum_positive(xs):\n    return sum(x for x in xs if x > 0)\n```"
SUM_ARR_CODE = "```python\ndef sum_arr(arr):\n    return sum(arr)\n```"
AUDIT_ASK = "DECISION: ASK\nQUESTION: Should negative numbers be rejected?"

SUBTRACT = {
    "prompt": "Write a function to subtract the elements of the given nested tuples.",
    "entry_point": "substract_elements",
}
SUBTRACT_AUDIT = (
    "DECISION: ASK\nQUESTION: Should the inner tuples of the two sequences be subtracted "
    "element-wise?"
)
SUBTRACT_ANSWER = (
    "Yes: subtract the corresponding elements of corresponding inner tuples, keeping the nesting."
)


def _signature(prompt, entry_point):
    return infer_signature(prompt, entry_point, extract_examples(prompt, entry_point))


def _certificate(prompt, entry_point, smt):
    defines, statements = parse_smt_statements(smt, prompt)
    return smt_certificate(_signature(prompt, entry_point), defines, statements, entry_point)


class SortsAndValuesTest(unittest.TestCase):
    def test_hint_sorts(self):
        hint = lambda text: hint_sort(ast.parse(text, mode="eval").body)  # noqa: E731
        self.assertEqual(hint("int"), "Int")
        self.assertEqual(hint("List[float]"), "(Seq Real)")
        self.assertEqual(hint("list"), "(Seq ?)")
        self.assertEqual(hint("Tuple[int, int]"), "(Seq Int)")
        self.assertIsNone(hint("Tuple[int, str]"))
        self.assertIsNone(hint("Optional[int]"))

    def test_value_sorts_and_unification(self):
        self.assertEqual(value_sort([[1], [2.5]]), "(Seq (Seq Real))")
        self.assertEqual(value_sort([]), "(Seq ?)")
        self.assertEqual(unify(["(Seq ?)", "(Seq Int)"]), "(Seq Int)")
        self.assertIsNone(unify(["Int", "String"]))

    def test_smt_values(self):
        self.assertEqual(smt_value(-3, "Int"), "(- 3)")
        self.assertEqual(smt_value(3.0, "Int"), "3")  # tests compare with ==: 3 == 3.0
        self.assertEqual(smt_value(-0.25, "Real"), "(- (/ 1.0 4.0))")
        self.assertEqual(smt_value(1, "Bool"), "true")  # True == 1
        self.assertEqual(smt_value('a"b\\', "String"), '"a""b\\u{5c}"')
        self.assertEqual(smt_value([], "(Seq Int)"), "(as seq.empty (Seq Int))")
        self.assertEqual(smt_value([1, 2], "(Seq Int)"), "(seq.++ (seq.unit 1) (seq.unit 2))")
        self.assertIsNone(smt_value("False", "Bool"))
        self.assertIsNone(smt_value(float("nan"), "Real"))

    def test_signature_from_hints_and_from_examples(self):
        sig = _signature(TRUNC_PROMPT, "truncate_number")
        self.assertEqual((sig["arg_sorts"], sig["result_sort"]), (["Real"], "Real"))
        untyped = 'def count(s):\n    """ Count.\n    >>> count("ab")\n    2\n    """\n'
        sig = _signature(untyped, "count")
        self.assertEqual((sig["arg_sorts"], sig["result_sort"]), (["String"], "Int"))
        self.assertIsNone(sig["result_hinted"])


class TypeClashTest(unittest.TestCase):
    def test_hint_violated_by_an_example_is_certified_without_llm(self):
        prompt = (
            'def is_even(n: int) -> bool:\n    """ Even?\n    >>> is_even(2)\n    "True"\n    """\n'
        )
        clash = type_clash(_signature(prompt, "is_even"), "is_even")
        self.assertEqual(clash["kind"], "type")
        self.assertIn("returns `bool`", clash["question"])
        self.assertEqual(clash["question"].count("?"), 1)

    def test_python_equality_is_not_a_clash(self):
        prompt = 'def half(n: int) -> float:\n    """ Half.\n    >>> half(4)\n    2\n    """\n'
        self.assertIsNone(type_clash(_signature(prompt, "half"), "half"))


class ReadingsParsingTest(unittest.TestCase):
    def test_audit_defects(self):
        self.assertEqual(len(audit_defects(COUNT_AUDIT)), 1)
        self.assertEqual(audit_defects("STEP 1 - DEFECTS\n- none\nDECISION: CODE"), [])

    def test_definition_signature(self):
        self.assertEqual(
            definition_signature("(define-fun f ((xs (Seq Int)) (k Int)) Int 0)"),
            ("f", ["(Seq Int)", "Int"], "Int"),
        )
        self.assertIsNone(definition_signature("(define-fun f ((x Int)) Int (assert true))"))
        self.assertIsNone(definition_signature("(define-fun f ((x Int)) Int"))

    def test_parse_readings_keeps_only_complete_ambiguities(self):
        response = COUNT_READINGS + 'AMBIGUITY "list"\nREADING A: a list\nREADING B: a tuple\n'
        helpers, ambiguities = parse_readings(response, COUNT["prompt"])
        self.assertEqual(helpers, [])
        self.assertEqual([a["quote"] for a in ambiguities], ["greater than"])
        self.assertEqual(ambiguities[0]["A"], "count only elements strictly greater than k")

    @unittest.skipUnless(HAS_Z3, "z3-solver not installed")
    def test_analysis_witness_equivalence_and_choice(self):
        helpers, ambiguities = parse_readings(COUNT_READINGS, COUNT["prompt"])
        (result,) = analyse_readings(helpers, ambiguities, None)
        args, value_a, value_b = result["witness"]
        self.assertTrue(result["ordinary"])
        self.assertLess(value_a, value_b)  # ">= k" also counts the elements equal to k
        self.assertIn(args[1], args[0])  # an element equal to k is what separates the readings
        self.assertGreater(result["rate"], 0)
        self.assertIs(choose_ambiguity([result], "Should elements equal to k be counted?"), result)
        self.assertIsNone(choose_ambiguity([result], "Does it take a list and k?"))
        helpers, ambiguities = parse_readings(POSITIVE_READINGS, POSITIVE["prompt"])
        (equivalent,) = analyse_readings(helpers, ambiguities, None)
        self.assertTrue(equivalent.get("equivalent"))
        self.assertIsNone(choose_ambiguity([equivalent], "Should zero count?"))

    @unittest.skipUnless(HAS_Z3, "z3-solver not installed")
    def test_readings_with_different_parameters_are_skipped(self):
        response = COUNT_READINGS.replace(
            "fb ((xs (Seq Int)) (k Int)) Int", "fb ((xs (Seq Int))) Int"
        )
        helpers, ambiguities = parse_readings(response, COUNT["prompt"])
        self.assertEqual(analyse_readings(helpers, ambiguities, None), [])


class ParsingTest(unittest.TestCase):
    def test_statements_need_verified_quotes_and_parenthesised_formulas(self):
        response = (
            "```smt2\n"
            '- **STATEMENT** "Return the decimal part of the number."\n'
            "ASSERT (assert (forall ((x Real)) (= (f x) 0.5)))\n"
            'STATEMENT "Return the integer part."\n'  # not in the task: dropped with its ASSERT
            "ASSERT (forall ((x Real)) (= (f x) 1.0))\n"
            "DEFINE (define-fun g ((x Real)) Real x)\n"
            "```\n"
        )
        defines, statements = parse_smt_statements(response, TRUNC_PROMPT)
        self.assertEqual(defines, ["(define-fun g ((x Real)) Real x)"])
        self.assertEqual(len(statements), 1)
        self.assertEqual(statements[0]["formulas"], ["(assert (forall ((x Real)) (= (f x) 0.5)))"])


@unittest.skipUnless(HAS_Z3, "z3-solver not installed")
class SmtCertificateTest(unittest.TestCase):
    def test_statement_vs_example_with_the_implied_value(self):
        certificate = _certificate(TRUNC_PROMPT, "truncate_number", TRUNC_SMT)
        self.assertEqual(certificate["kind"], "smt")
        self.assertEqual(certificate["implied"], 0.5)
        self.assertEqual(
            certificate["question"],
            'The task says "Return the decimal part of the number.", which gives '
            '`truncate_number(3.5) == 0.5`, but the example says "truncate_number(3.5) == 3". '
            "Which is intended?",
        )

    def test_recursive_helper_and_quantifier_over_sequences(self):
        certificate = _certificate(SUM_PROMPT, "total", SUM_SMT)
        self.assertEqual(certificate["implied"], 6)
        consistent = SUM_PROMPT.replace("    7\n", "    6\n")
        self.assertIsNone(_certificate(consistent, "total", SUM_SMT))

    def test_examples_that_disagree_on_one_input(self):
        prompt = 'def g(n: int) -> int:\n    """ Something.\n    >>> g(2)\n    4\n    g(2) == 5\n    """\n'
        smt = 'STATEMENT "Something."\nASSERT (forall ((n Int)) (>= (f n) 0))\n'
        self.assertEqual(_certificate(prompt, "g", smt)["kind"], "examples")

    def test_unparseable_or_self_contradictory_formulas_prove_nothing(self):
        garbage = TRUNC_SMT.replace("(- x (to_real (to_int x)))", "(frobnicate x)")
        self.assertIsNone(_certificate(TRUNC_PROMPT, "truncate_number", garbage))
        contradictory = (
            'STATEMENT "Return the decimal part of the number."\n'
            "ASSERT (and (= (f 1.0) 0.0) (= (f 1.0) 1.0))\n"
        )
        self.assertIsNone(_certificate(TRUNC_PROMPT, "truncate_number", contradictory))

    def test_commands_inside_a_formula_are_rejected(self):
        sneaky = TRUNC_SMT.replace(
            "ASSERT (forall", "ASSERT (and (check-sat) true)\nASSERT (forall"
        )
        certificate = _certificate(TRUNC_PROMPT, "truncate_number", sneaky)
        self.assertEqual(certificate["kind"], "smt")  # the bad formula is dropped, the rest holds


class _FakeEnv:
    def __init__(self, llm_responses, answer="The decimal part.", **kw):
        self.llm_responses = list(llm_responses)
        self.answer = answer
        self.raise_at = kw.get("raise_at", {})
        self.exec_mode = kw.get("exec_mode", "real")
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


class RunTest(unittest.TestCase):
    def test_pinpoint_prompts_are_unchanged(self):
        for name in ("AUDIT_TEMPLATE", "CODING_RULES", "CODE_TEMPLATE", "REPAIR_TEMPLATE"):
            self.assertEqual(getattr(laaser_pinpoint, name), getattr(laaser_pinpoint_smt, name))

    def test_no_examples_means_exactly_pinpoint(self):
        env = _FakeEnv([AUDIT_ASK, SUM_ARR_CODE])
        result = _algo().run(env, MBPP)
        self.assertIn("def sum_arr", result)
        self.assertEqual(len(env.prompts), 2)  # audit, code: no formalization call
        self.assertEqual(env.questions, ["Should negative numbers be rejected?"])

    @unittest.skipUnless(HAS_Z3, "z3-solver not installed")
    def test_code_decision_is_rescued_by_a_proven_contradiction(self):
        env = _FakeEnv(["DECISION: CODE\n" + TRUNC_CODE, TRUNC_SMT, TRUNC_CODE])
        result = _algo().run(env, TRUNC)
        self.assertIn("def truncate_number", result)
        self.assertEqual(len(env.questions), 1)
        self.assertIn("which gives `truncate_number(3.5) == 0.5`", env.questions[0])
        self.assertIn("(declare-fun f (Real) Real)", env.prompts[1])
        self.assertEqual(env.exec_calls, 0)

    @unittest.skipUnless(HAS_Z3, "z3-solver not installed")
    def test_certificate_replaces_an_unrelated_audit_question_in_solver_mode(self):
        env = _FakeEnv([AUDIT_ASK, TRUNC_SMT, TRUNC_CODE])
        _algo(question_source="solver").run(env, TRUNC)
        self.assertIn("but the example says", env.questions[0])

    def test_audit_mode_leaves_an_asked_question_alone_without_extra_calls(self):
        env = _FakeEnv([AUDIT_ASK, TRUNC_CODE])
        _algo(question_source="audit").run(env, TRUNC)
        self.assertEqual(env.questions, ["Should negative numbers be rejected?"])
        self.assertEqual(len(env.prompts), 2)  # audit, code

    @unittest.skipUnless(HAS_Z3, "z3-solver not installed")
    def test_diverging_readings_become_a_concrete_question(self):
        env = _FakeEnv([COUNT_AUDIT, COUNT_READINGS, COUNT_CODE], answer="Strictly greater.")
        result = _algo(question_source="solver").run(env, COUNT)
        self.assertIn("def count_greater", result)
        self.assertIn("- VAGUE", env.prompts[1])  # the audit's places reach the formalization
        question = env.questions[0]
        self.assertTrue(
            question.startswith(
                'The task says "greater than". For example, should `count_greater(['
            ),
            question,
        )
        self.assertIn("(count only elements strictly greater than k) or ", question)
        self.assertEqual(question.count("?"), 1)

    @unittest.skipUnless(HAS_Z3, "z3-solver not installed")
    def test_equivalent_readings_keep_the_audit_question(self):
        env = _FakeEnv([POSITIVE_AUDIT, POSITIVE_READINGS, POSITIVE_CODE])
        _algo(question_source="solver").run(env, POSITIVE)
        self.assertEqual(env.questions, ["Should zero count as a positive number?"])

    @unittest.skipUnless(HAS_Z3, "z3-solver not installed")
    def test_a_question_the_solver_cannot_map_is_kept(self):
        audit = COUNT_AUDIT.replace(
            "Should elements equal to k be counted?", "Does the function take a list and k?"
        )
        env = _FakeEnv([audit, COUNT_READINGS, COUNT_CODE])
        _algo(question_source="solver").run(env, COUNT)
        self.assertEqual(env.questions, ["Does the function take a list and k?"])

    @unittest.skipUnless(HAS_Z3, "z3-solver not installed")
    def test_audit_coding_is_rescued_by_an_ordinary_witness(self):
        audit = COUNT_AUDIT.split("DECISION:")[0] + "DECISION: CODE\n" + COUNT_CODE
        env = _FakeEnv([audit, COUNT_READINGS, COUNT_CODE])
        _algo().run(env, COUNT)
        self.assertEqual(len(env.questions), 1)
        self.assertIn("For example, should `count_greater(", env.questions[0])

    def test_type_clash_needs_neither_llm_nor_z3(self):
        prompt = (
            'def is_even(n: int) -> bool:\n    """ Even?\n    >>> is_even(2)\n    "True"\n    """\n'
        )
        code = "```python\ndef is_even(n):\n    return n % 2 == 0\n```"
        saved, laaser_pinpoint_smt.z3 = laaser_pinpoint_smt.z3, None
        try:
            env = _FakeEnv(["DECISION: CODE\n" + code, code])
            _algo().run(env, {"prompt": prompt, "entry_point": "is_even"})
        finally:
            laaser_pinpoint_smt.z3 = saved
        self.assertEqual(len(env.prompts), 2)  # audit, code: no formalization call
        self.assertIn("says it returns `bool`", env.questions[0])

    def test_without_z3_the_formalization_is_skipped(self):
        saved, laaser_pinpoint_smt.z3 = laaser_pinpoint_smt.z3, None
        try:
            env = _FakeEnv(["DECISION: CODE\n" + TRUNC_CODE])
            result = _algo().run(env, TRUNC)
        finally:
            laaser_pinpoint_smt.z3 = saved
        self.assertIn("def truncate_number", result)
        self.assertEqual((len(env.prompts), env.questions), (1, []))

    def test_formalization_failure_falls_back_to_pinpoint(self):
        env = _FakeEnv([AUDIT_ASK, TRUNC_CODE], raise_at={1: LimitsExceededException("budget")})
        _algo(question_source="solver").run(env, TRUNC)
        self.assertEqual(env.questions, ["Should negative numbers be rejected?"])

    def test_stub_from_the_coder_goes_through_repair(self):
        stub = "```python\ndef sum_arr(arr):\n    return\n```"
        env = _FakeEnv([AUDIT_ASK, stub, SUM_ARR_CODE])
        result = _algo().run(env, MBPP)
        self.assertIn("return sum(arr)", result)
        self.assertIn("does nothing", env.prompts[-1])

    def test_default_mode_is_pinpoint_when_the_audit_asks(self):
        env = _FakeEnv([COUNT_AUDIT, COUNT_CODE])
        _algo().run(env, COUNT)
        self.assertEqual(env.questions, ["Should elements equal to k be counted?"])
        self.assertEqual(len(env.prompts), 2)  # audit, code: no solver call

    def test_persistent_placeholder_is_recoded_without_the_clarification(self):
        stub = "```python\ndef sum_arr(arr):\n    return\n```"
        env = _FakeEnv([AUDIT_ASK, stub, stub, stub, SUM_ARR_CODE], answer="Yes.")
        result = _algo().run(env, MBPP)
        self.assertIn("return sum(arr)", result)
        self.assertIn("Earlier attempts did not produce a working function", env.prompts[-1])
        self.assertNotIn("Answer:", env.prompts[-1])

    def test_constant_return_ignoring_the_arguments_is_repaired(self):
        constant = "```python\ndef sum_arr(arr):\n    return 0\n```"
        env = _FakeEnv([AUDIT_ASK, constant, SUM_ARR_CODE])
        result = _algo().run(env, MBPP)
        self.assertIn("return sum(arr)", result)
        self.assertIn("ignores its arguments", env.prompts[-1])

    def test_a_constant_the_model_insists_on_is_kept_without_fallback(self):
        constant = "```python\ndef sum_arr(arr):\n    return 7\n```"
        env = _FakeEnv([AUDIT_ASK, constant, constant, constant], answer="Always return 7.")
        self.assertIn("return 7", _algo().run(env, MBPP))
        self.assertEqual(len(env.prompts), 4)  # audit, code, two repairs: no fallback

    def test_non_answers_do_not_steer_the_code(self):
        for answer in (
            "Your question bundles two separate clarifications; please ask them separately.",
            "I can't confirm the exact behavior without more context.",
            "",
        ):
            env = _FakeEnv([AUDIT_ASK, SUM_ARR_CODE], answer=answer)
            _algo().run(env, MBPP)
            self.assertIn("got no usable answer", env.prompts[-1], answer)
            self.assertNotIn("Answer:", env.prompts[-1])
        env = _FakeEnv([AUDIT_ASK, SUM_ARR_CODE], answer="Yes, reject them.")
        _algo().run(env, MBPP)
        self.assertIn("Answer: Yes, reject them.", env.prompts[-1])

    def test_bundled_audit_question_is_cut_to_its_first_question(self):
        audit = "DECISION: ASK\nQUESTION: Tuple or list? Also, should duplicates be kept?"
        env = _FakeEnv([audit, SUM_ARR_CODE])
        _algo().run(env, MBPP)
        self.assertEqual(env.questions, ["Tuple or list?"])
        env = _FakeEnv([audit, SUM_ARR_CODE])
        _algo(atomic_question=False).run(env, MBPP)
        self.assertEqual(env.questions, ["Tuple or list? Also, should duplicates be kept?"])

    def test_probe_calls_must_be_literal_calls_of_the_entry_point(self):
        response = (
            "CALL sum_arr([1, 2, 3])\n"
            "- `CALL sum_arr([])`\n"
            "CALL sum_arr(xs)\n"  # not a literal
            "CALL other([1])\n"  # another function
            "CALL sum_arr(arr=[1])\n"  # keywords are not used by the tests
        )
        self.assertEqual(
            parse_probe_calls(response, "sum_arr"),
            [
                ("sum_arr([1, 2, 3])", ([1, 2, 3],), (False, None)),
                ("sum_arr([])", ([],), (False, None)),
            ],
        )
        expected = parse_probe_calls(
            "CALL sum_arr([1, 2]) == 3\nCALL sum_arr([1]) < 3\nCALL sum_arr([2]) == x", "sum_arr"
        )
        self.assertEqual(
            expected,
            [
                ("sum_arr([1, 2])", ([1, 2],), (True, 3)),
                ("sum_arr([1])", ([1],), (False, None)),  # not an equality: call only
                ("sum_arr([2])", ([2],), (False, None)),  # not a literal: call only
            ],
        )

    def test_probe_lines_without_the_call_tag(self):
        # How gpt-4.1-mini really answered on a smoke run: 198 of 210 lines had no CALL tag.
        response = (
            "first_even([1, 3, 4, 6]) == 4\n"
            "1. first_even([2, 5]) == 2\n"
            "- `first_even([7])`\n"
            "assert first_even([8, 1]) == 8\n"
            ">>> first_even([6])\n"
            "first_even([4, 4]) -> 4\n"
            "even_Power_Sum(2) == 16 + 256\n"
            "first_even([3]) == 2 ** 4\n"
            "Here are the calls:\n"
            "```python\n"
        )
        calls = parse_probe_calls(response, "first_even")
        self.assertEqual(
            [(text, expected) for text, _, expected in calls],
            [
                ("first_even([1, 3, 4, 6])", (True, 4)),
                ("first_even([2, 5])", (True, 2)),
                ("first_even([7])", (False, None)),
                ("first_even([8, 1])", (True, 8)),
                ("first_even([6])", (False, None)),
                ("first_even([4, 4])", (True, 4)),
                ("first_even([3])", (True, 16)),
            ],
        )
        self.assertEqual(parse_probe_calls(response, "even_Power_Sum")[0][2], (True, 272))

    def test_result_lines_are_read_in_order(self):
        response = "RESULT ((1, 2),)\n- RESULT: UNSURE\nRESULT [3, 4]  \nRESULT not python"
        self.assertEqual(
            parse_results(response, 5),
            [(True, ((1, 2),)), (False, None), (True, [3, 4]), (False, None), (False, None)],
        )
        untagged = "Here are the results:\n```\n((1, 2),)\nUNSURE\nf(3) == 'x'\n16 + 256\n```"
        self.assertEqual(
            parse_results(untagged, 4),
            [(True, ((1, 2),)), (False, None), (True, "x"), (True, 272)],
        )

    def test_same_shape_compares_kinds_not_values(self):
        self.assertTrue(same_shape(((-5, -4), (1, -4)), [[-9, 3]]))  # values and lengths aside
        self.assertTrue(same_shape({3, 1}, [1, 3, 5]))
        self.assertTrue(same_shape(3, 4.5))
        self.assertTrue(same_shape(True, 0))  # tests compare with ==: True == 1
        self.assertTrue(same_shape([], [(1, 2)]))
        self.assertTrue(same_shape({"a": (1, 2)}, {"a": [3], "b": "x"}))
        self.assertFalse(same_shape(((-5, -4), (1, -4)), [-9, -3]))  # pairs vs numbers
        self.assertFalse(same_shape("0 1 2", ["0", "1", "2"]))
        self.assertFalse(same_shape("1", 1))
        self.assertFalse(same_shape(None, 0))
        self.assertFalse(same_shape({"a": 1}, [("a", 1)]))
        self.assertFalse(same_shape({"a": 1}, {"a": "1"}))

    def test_non_answers_are_refusals_not_answers_with_the_same_words(self):
        for reply in (
            "Your question bundles two separate clarifications; please ask them separately.",
            "Please ask one question at a time.",
            "That's a bit broad; could you please ask about one specific aspect of the format?",
            "I can't confirm the exact behavior.",
            "",
        ):
            self.assertFalse(usable_answer(reply), reply)
        for reply in (
            "The bucket capacity applies per well, meaning each well is emptied separately.",
            "All occurrences of the digit 7 in each integer should be counted separately.",
            "If the list is empty the function can't determine a maximum, so it returns None.",
        ):
            self.assertTrue(usable_answer(reply), reply)

    def test_tolerate_extra_args_edits_only_the_signature(self):
        cases = {
            "def f(a, b=2):\n    return a + b\n": "def f(a, b=2, *extra_args):",
            "def f(a: int, b: 'List[int]' = None) -> int:\n    return a\n": (
                "def f(a: int, b: 'List[int]' = None, *extra_args) -> int:"
            ),
            "def f():\n    return 1\n": "def f(*extra_args):",
            "def f(**kw):\n    return kw\n": "def f(*extra_args, **kw):",
            "def f(a, /, b):\n    return a\n": "def f(a, /, b, *extra_args):",
            "async def f(x='\u00e9'):\n    return x\n": "async def f(x='\u00e9', *extra_args):",
            "def f(a,\n      b=(1,\n         2)):\n    return b\n": "         2), *extra_args):",
            "@decorator\ndef f(a):\n    return a\n": "def f(a, *extra_args):",
            "def f(a):\n    return 0\n\ndef f(a, b):\n    return b\n": "def f(a, b, *extra_args):",
        }
        for code, signature in cases.items():
            self.assertIn(signature, tolerate_extra_args(code, "f"), code)
        for unchanged in (
            "def f(*args):\n    return args\n",
            "def f(a, *, key=None):\n    return a\n",
            "def f(a, /):\n    return a\n",
            "def g(a):\n    return a\n\nf = g\n",
            "def f(a):\n    return (\n",
        ):
            self.assertEqual(tolerate_extra_args(unchanged, "f"), unchanged)

    def test_tolerated_extra_args_are_ignored_and_nothing_else_changes(self):
        namespace: dict = {}
        exec(tolerate_extra_args("def f(xs, k=1):\n    return sum(xs) * k\n", "f"), namespace)
        f = namespace["f"]
        self.assertEqual((f([1, 2]), f([1, 2], 3), f([1, 2], 3, 99, "n")), (3, 9, 9))
        with self.assertRaises(TypeError):
            f()  # a missing argument is still an error

    def test_execution_check_repairs_a_signature_the_answer_contradicts(self):
        one_arg = "```python\ndef sub(seq):\n    return tuple(a - b for a, b in seq)\n```"
        two_args = (
            "```python\ndef sub(s1, s2):\n"
            "    return tuple(tuple(a - b for a, b in zip(x, y)) for x, y in zip(s1, s2))\n```"
        )
        probes = "CALL sub(((1, 3), (4, 5)), ((6, 7), (3, 9)))\nCALL sub(((1, 1),), ((0, 1),))"
        problem = {"prompt": "Write a function to subtract elements.", "entry_point": "sub"}
        env = _FakeEnv(
            ["DECISION: ASK\nQUESTION: One or two sequences?", one_arg, probes, two_args],
            answer="It takes two sequences of tuples and subtracts them element-wise.",
        )
        result = _algo(verify=True).run(env, problem)
        self.assertIn("def sub(s1, s2)", result)
        self.assertIn("takes 1 positional argument but 2 were given", env.prompts[-1])
        self.assertEqual(env.exec_calls, 2)  # the original, then the repair

    def test_execution_check_catches_a_function_that_never_returns(self):
        silent = "```python\ndef sum_arr(arr):\n    total = sum(arr)\n```"
        probes = "CALL sum_arr([1, 2])\nCALL sum_arr([3])"
        env = _FakeEnv([AUDIT_ASK, silent, probes, SUM_ARR_CODE], answer="Yes.")
        result = _algo(verify=True).run(env, MBPP)
        self.assertIn("return sum(arr)", result)
        self.assertIn("returns None for every call", env.prompts[-1])

    def test_a_repair_that_does_not_help_is_discarded(self):
        crashing = "```python\ndef sum_arr(arr):\n    return arr.total()\n```"
        probes = "CALL sum_arr([1, 2])"
        env = _FakeEnv([AUDIT_ASK, crashing, probes, crashing], answer="Yes.")
        result = _algo(verify=True).run(env, MBPP)
        self.assertIn("arr.total()", result)
        self.assertEqual(env.exec_calls, 2)

    def test_intentional_value_errors_and_a_broken_sandbox_change_nothing(self):
        strict = (
            "```python\ndef sum_arr(arr):\n    if not arr:\n        raise ValueError('empty')"
            "\n    return sum(arr)\n```"
        )
        env = _FakeEnv([AUDIT_ASK, strict, "CALL sum_arr([])\nCALL sum_arr([1])"], answer="Yes.")
        self.assertIn("raise ValueError", _algo(verify=True).run(env, MBPP))
        self.assertEqual((env.exec_calls, len(env.prompts)), (1, 3))  # no repair call
        env = _FakeEnv([AUDIT_ASK, SUM_ARR_CODE, "CALL sum_arr([1])"], exec_mode="raise")
        self.assertIn("return sum(arr)", _algo(verify=True).run(env, MBPP))

    def test_a_result_contradicting_the_answer_is_repaired(self):
        # Mbpp/888: the user answered "element-wise", the code summed the differences.
        wrong = (
            "```python\ndef substract_elements(seq1, seq2):\n"
            "    return [(a[0] - b[0]) + (a[1] - b[1]) for a, b in zip(seq1, seq2)]\n```"
        )
        right = (
            "```python\ndef substract_elements(seq1, seq2):\n"
            "    return tuple(tuple(x - y for x, y in zip(a, b)) for a, b in zip(seq1, seq2))\n```"
        )
        probes = (
            "CALL substract_elements(((1, 3), (4, 5)), ((6, 7), (3, 9))) == ((-5, -4), (1, -4))\n"
            "CALL substract_elements(((2, 2),), ((1, 1),)) == ((1, 1),)"
        )
        results = "RESULT ((-5, -4), (1, -4))\nRESULT [[1, 1]]"  # agrees, as a list
        env = _FakeEnv([SUBTRACT_AUDIT, wrong, probes, results, right], answer=SUBTRACT_ANSWER)
        result = _algo(verify=True).run(env, SUBTRACT)
        self.assertIn("tuple(x - y", result)
        self.assertIn("implies a result like ((-5, -4), (1, -4))", env.prompts[-1])
        self.assertIn("but the code returns [-9, -3], a different kind of value", env.prompts[-1])
        self.assertIn("substract_elements(((2, 2),), ((1, 1),))", env.prompts[3])
        self.assertEqual(env.exec_calls, 2)

    def test_results_the_two_derivations_disagree_on_are_not_checked(self):
        wrong = "```python\ndef substract_elements(seq1, seq2):\n    return [0 for _ in seq1]\n```"
        probes = "CALL substract_elements(((1, 3),), ((6, 7),)) == ((-5, -4),)"
        env = _FakeEnv([SUBTRACT_AUDIT, wrong, probes, "RESULT [-9]"], answer=SUBTRACT_ANSWER)
        self.assertIn("[0 for _ in seq1]", _algo(verify=True).run(env, SUBTRACT))
        self.assertEqual((len(env.prompts), env.exec_calls), (4, 1))  # no repair

    def test_the_same_values_in_another_container_need_no_repair(self):
        lists = (
            "```python\ndef substract_elements(seq1, seq2):\n"
            "    return [[x - y for x, y in zip(a, b)] for a, b in zip(seq1, seq2)]\n```"
        )
        probes = "CALL substract_elements(((1, 3),), ((6, 7),)) == ((-5, -4),)"
        env = _FakeEnv(
            [SUBTRACT_AUDIT, lists, probes, "RESULT ((-5, -4),)"], answer=SUBTRACT_ANSWER
        )
        self.assertIn("[[x - y", _algo(verify=True).run(env, SUBTRACT))
        self.assertEqual((len(env.prompts), env.exec_calls), (4, 1))

    def test_without_a_real_answer_only_crashes_are_checked(self):
        wrong = "```python\ndef substract_elements(seq1, seq2):\n    return [0 for _ in seq1]\n```"
        probes = "CALL substract_elements(((1, 3),), ((6, 7),)) == ((-5, -4),)"
        env = _FakeEnv([SUBTRACT_AUDIT, wrong, probes], answer="Please ask one question at a time.")
        self.assertIn("[0 for _ in seq1]", _algo(verify=True).run(env, SUBTRACT))
        self.assertEqual((len(env.prompts), env.exec_calls), (3, 1))  # no second derivation

    def test_a_repair_that_crashes_on_a_new_call_is_discarded(self):
        text = "```python\ndef sum_arr(arr):\n    return str(sum(arr)) if arr else 0\n```"
        fragile = "```python\ndef sum_arr(arr):\n    return arr[0] + sum(arr[1:])\n```"
        probes = "CALL sum_arr([1, 2]) == 3\nCALL sum_arr([5]) == 5\nCALL sum_arr([]) == 0"
        results = "RESULT 3\nRESULT 5\nRESULT 0"
        env = _FakeEnv([AUDIT_ASK, text, probes, results, fragile], answer="No.")
        self.assertIn("str(sum(arr))", _algo(verify=True).run(env, MBPP))
        self.assertEqual(env.exec_calls, 2)  # fixes two kinds of result, but crashes on []

    def test_a_wrong_value_the_arbitration_rejects_is_left_alone(self):
        # The model's own arithmetic is not trusted on its own: fizz_buzz(150) "== 3" (it is 4).
        right = "```python\ndef sum_arr(arr):\n    return sum(arr)\n```"
        probes = "sum_arr([1, 2]) == 4\nsum_arr([5]) == 5"
        verdict = "1 + 2 = 3, so A is right.\nCORRECT: A"
        env = _FakeEnv([AUDIT_ASK, right, probes, "RESULT 4\nRESULT 5", verdict], answer="No.")
        self.assertIn("return sum(arr)", _algo(verify=True).run(env, MBPP))
        self.assertEqual((len(env.prompts), env.exec_calls), (5, 1))  # no repair
        self.assertIn("A: 3\nB: 4", env.prompts[-1])

    def test_a_value_the_code_misreads_is_repaired_when_the_arbitration_agrees(self):
        # Mbpp/368: "the entire tuple repeated n times as separate elements".
        misread = (
            "```python\ndef repeat_tuples(tpl, n):\n    return tuple((x,) * n for x in tpl)\n```"
        )
        right = (
            "```python\ndef repeat_tuples(tpl, n):\n    return tuple(tpl for _ in range(n))\n```"
        )
        probes = (
            "repeat_tuples((1, 2), 3) == ((1, 2), (1, 2), (1, 2))\n"
            "repeat_tuples((), 2) == ((), ())\n"
            "repeat_tuples(('a',), 1) == (('a',),)"
        )
        results = "RESULT (((1, 2), (1, 2), (1, 2)))\nRESULT ((), ())\nRESULT (('a',),)"
        verdict = "The whole tuple is repeated three times.\n**CORRECT: B**"
        problem = {
            "prompt": "Write a function to repeat the given tuple n times.",
            "entry_point": "repeat_tuples",
        }
        env = _FakeEnv(
            [AUDIT_ASK, misread, probes, results, verdict, right],
            answer="The entire input tuple is repeated n times as separate elements.",
        )
        result = _algo(verify=True).run(env, problem)
        self.assertIn("tuple(tpl for _ in range(n))", result)
        self.assertIn("A: ((1, 1, 1), (2, 2, 2))\nB: ((1, 2), (1, 2), (1, 2))", env.prompts[4])
        self.assertIn(
            "implies ((1, 2), (1, 2), (1, 2)), but the code returns ((1, 1, 1), (2, 2, 2))",
            env.prompts[-1],
        )
        self.assertEqual(env.exec_calls, 2)

    def test_same_value_is_lenient_about_containers_and_floats(self):
        self.assertTrue(same_value(((1, 2), (1, 2)), [[1, 2], [1, 2]]))
        self.assertTrue(same_value({3, 1}, [1, 3]))
        self.assertTrue(same_value(0.1 + 0.2, 0.3))
        self.assertFalse(same_value(((1, 1, 1), (2, 2, 2)), ((1, 2), (1, 2), (1, 2))))
        self.assertFalse(same_value([1, 2], [2, 1]))
        self.assertFalse(same_value("1", 1))

    def test_the_checklist_shows_only_the_entries_the_task_mentions(self):
        block = checklist_block("Write a function to repeat the given tuple n times.")
        self.assertIn("Tuples: a pair or any length?", block)
        self.assertNotIn("Text:", block)
        self.assertEqual(checklist_block("Write a function to do it."), "")
        long_task = "Sort the list of strings, count the words, find the first prime, round it."
        self.assertEqual(checklist_block(long_task).count("\n- "), 5)  # at most 5 entries

    def test_the_checklist_audit_extends_pinpoint_and_is_optional(self):
        self.assertTrue(AUDIT_CHECKLIST_TEMPLATE.startswith(AUDIT_TEMPLATE.split("Write one")[0]))
        problem = {
            "prompt": "Write a function to repeat the given tuple n times.",
            "entry_point": "repeat_tuples",
        }
        code = "```python\ndef repeat_tuples(t, n):\n    return (t,) * n\n```"
        env = _FakeEnv([AUDIT_ASK, code], answer="A tuple of tuples.")
        _algo(checklist=True).run(env, problem)
        self.assertIn("- Tuples: a pair or any length?", env.prompts[0])
        self.assertIn("Python literals for one small input", env.prompts[0])
        self.assertNotIn("{checklist}", env.prompts[0])
        env = _FakeEnv([AUDIT_ASK, code], answer="A tuple of tuples.")
        _algo().run(env, problem)
        self.assertNotIn("Tuples: a pair", env.prompts[0])
        self.assertNotIn("Python literals for one small input", env.prompts[0])

    def test_a_guessed_call_with_too_few_arguments_is_not_a_bug(self):
        two = "```python\ndef sum_arr(arr, n):\n    return sum(arr[:n])\n```"
        env = _FakeEnv([AUDIT_ASK, two, "sum_arr([1, 2])\nsum_arr([3])"], answer="No.")
        self.assertIn("arr[:n]", _algo(verify=True).run(env, MBPP))
        self.assertEqual((len(env.prompts), env.exec_calls), (3, 1))  # no repair

    def test_an_iterator_instead_of_a_value_is_repaired(self):
        lazy = "```python\ndef sum_arr(arr):\n    return (x for x in arr)\n```"
        env = _FakeEnv([AUDIT_ASK, lazy, "sum_arr([1, 2])", SUM_ARR_CODE], answer="No.")
        self.assertIn("return sum(arr)", _algo(verify=True).run(env, MBPP))
        self.assertIn("<generator object", env.prompts[-1])

    def test_the_returned_code_tolerates_extra_arguments(self):
        env = _FakeEnv([AUDIT_ASK, SUM_ARR_CODE], answer="No.")
        result = LAASeR_PinpointSMT({"verify": False}).run(env, MBPP)
        self.assertIn("def sum_arr(arr, *extra_args):", result)
        env = _FakeEnv([AUDIT_ASK, SUM_ARR_CODE], answer="No.")
        result = _algo().run(env, MBPP)
        self.assertIn("def sum_arr(arr):", result)

    def test_question_mentions_word_forms_and_literals(self):
        question = "Should it do the subtraction, or always return [9,9]?"
        self.assertTrue(question_mentions(question, ("subtract elements", "but return [9, 9].")))
        self.assertFalse(question_mentions("What about empty input?", ("subtract elements",)))


if __name__ == "__main__":
    unittest.main()