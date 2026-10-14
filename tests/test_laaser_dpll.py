"""Regression tests for clarify/algorithms/laaser_formal_dpll.py.

Offline, no network/Docker. Three layers:
1. The DPLL core (solve / backbone / minimal unsat core / peel_cores) is checked against
   brute-force enumeration on a few hundred seeded random CNFs.
2. The mechanical readers (formalization parser, example extractor, stub parser, question
   builder) are checked on hand-written and real dataset-style inputs.
3. run() is exercised end-to-end through a fake environment; the grounding script is executed
   for real in a subprocess (it uses signal.alarm, so it needs its own main thread).
"""

from __future__ import annotations

import itertools
import random
import subprocess
import sys
import unittest

from clarify.algorithms.laaser_formal_dpll import (
    LAASeR_FormalDPLL,
    atomic_question,
    backbone,
    build_question,
    dpll_solve,
    extract_examples,
    find_stub_params,
    minimal_unsat_core,
    parse_formalization,
    peel_cores,
    plan,
    quote_in_text,
)
from clarify.env import LimitsExceededException, TooManyQuestionException

# -------------------------------------------------------------------------------------------------
# Brute-force oracle
# -------------------------------------------------------------------------------------------------


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
        rng = random.Random(7)
        for _ in range(400):
            n, m = rng.randint(1, 7), rng.randint(0, 24)
            clauses = _random_cnf(rng, n, m)
            model = dpll_solve(clauses, n)
            brute = _models(clauses, n)
            self.assertEqual(model is None, not brute, clauses)
            if model is not None:
                self.assertEqual(set(model), set(range(1, n + 1)))
                for clause in clauses:
                    self.assertTrue(any(model[abs(lit)] == (lit > 0) for lit in clause))

    def test_backbone_agrees_with_brute_force(self):
        rng = random.Random(11)
        for _ in range(300):
            n, m = rng.randint(1, 6), rng.randint(0, 12)
            clauses = _random_cnf(rng, n, m)
            brute = _models(clauses, n)
            got = backbone(clauses, n)
            if not brute:
                self.assertIsNone(got)
                continue
            expected = {v: brute[0][v] for v in range(1, n + 1) if len({b[v] for b in brute}) == 1}
            self.assertEqual(got, expected, clauses)

    def test_minimal_unsat_core_is_unsat_and_minimal(self):
        rng = random.Random(3)
        checked = 0
        for _ in range(400):
            n = rng.randint(1, 5)
            groups = [_random_cnf(rng, n, rng.randint(1, 3)) for _ in range(rng.randint(1, 7))]
            core = minimal_unsat_core(groups, n)
            flat = [c for g in groups for c in g]
            if core is None:
                self.assertTrue(_models(flat, n))
                continue
            checked += 1
            self.assertFalse(_models([c for i in core for c in groups[i]], n))
            for drop in core:
                rest = [c for i in core if i != drop for c in groups[i]]
                self.assertTrue(_models(rest, n), "core is not minimal")
        self.assertGreater(checked, 50)

    def test_peel_cores_leaves_a_satisfiable_remainder(self):
        rng = random.Random(5)
        for _ in range(200):
            n = rng.randint(1, 5)
            groups = [_random_cnf(rng, n, rng.randint(1, 2)) for _ in range(rng.randint(1, 8))]
            cores, rest = peel_cores(groups, n)
            self.assertTrue(_models([c for i in rest for c in groups[i]], n))
            used = [i for core in cores for i in core]
            self.assertEqual(len(used), len(set(used)))
            self.assertFalse(set(used) & set(rest))

    def test_branching_follows_the_default_phase(self):
        exactly_one = [[1, 2], [-1, -2]]  # no pure literals: the solver must branch
        self.assertEqual(
            dpll_solve(exactly_one, 3, {1: False, 3: False}), {1: False, 2: True, 3: False}
        )
        self.assertEqual(dpll_solve(exactly_one, 2, {1: True}), {1: True, 2: False})

    def test_empty_clause_is_unsat(self):
        self.assertIsNone(dpll_solve([[]], 1))


# -------------------------------------------------------------------------------------------------
# Mechanical readers
# -------------------------------------------------------------------------------------------------

TASK = (
    "Write a function that moves all negative numbers before the positive ones. "
    "Keep the original relative order of the elements. "
    "The elements can be returned in any order."
)

FORMAL_CONTRADICTION = """
Some preamble the model writes anyway.
- ATOM keep_order | CONTRADICTION | HIGH | default A | "Keep the original relative order" | A: The result keeps the original relative order. | B: The elements may appear in any order.
ATOM zero_side | RULE | LOW | default B | "not stated" | A: zero counts as negative | B: zero counts as positive
CHECK keep_order | A: result == [x for x in arr if x < 0] + [x for x in arr if x >= 0] | B: sorted(result) == sorted(arr)
EVIDENCE "Keep the original relative order of the elements" => keep_order=A
EVIDENCE "The elements can be returned in any order" => keep_order=B
EVIDENCE "this sentence is not in the task at all" => zero_side=A
EVIDENCE "Keep the original relative order" => ghost_atom=A
DECISION: ASK
QUESTION: Should the order be kept? Also, where does zero go?
"""


class ReadersTest(unittest.TestCase):
    def test_parse_formalization_keeps_verified_evidence_only(self):
        formal = parse_formalization(FORMAL_CONTRADICTION, TASK, "move")
        self.assertEqual([a["name"] for a in formal["atoms"]], ["keep_order", "zero_side"])
        keep = formal["atoms"][0]
        self.assertEqual(
            (keep["kind"], keep["impact"], keep["default"]), ("CONTRADICTION", "HIGH", "A")
        )
        self.assertEqual(keep["A"], "the result keeps the original relative order")
        self.assertEqual(keep["phrase"], "Keep the original relative order")
        self.assertTrue(keep["check_A"].startswith("result =="))
        self.assertEqual(formal["atoms"][1]["phrase"], "")
        self.assertEqual(formal["atoms"][1]["impact"], "LOW")
        quotes = [e["quote"] for e in formal["evidence"]]
        # The invented quote and the unknown atom are both dropped.
        self.assertEqual(len(quotes), 2)
        self.assertNotIn("this sentence is not in the task at all", quotes)

    def test_kind_words_inside_the_phrase_do_not_change_the_kind(self):
        text = "Return the result in the standard format, with each rule applied once."
        line = 'ATOM fmt | VAGUE | HIGH | default A | "standard format" | A: a list | B: a tuple'
        formal = parse_formalization(line, text, "f")
        self.assertEqual(formal["atoms"][0]["kind"], "VAGUE")

    def test_parser_accepts_true_false_literals_and_reading_prefixes(self):
        text = "Return the decimal part of the number."
        response = (
            'ATOM part | FORMAT | HIGH | default A | "decimal part" | Reading A: the decimal part '
            "| Reading B: the integer part\n"
            'EVIDENCE "Return the decimal part" => part=TRUE\n'
        )
        formal = parse_formalization(response, text, "truncate")
        self.assertEqual(formal["atoms"][0]["B"], "the integer part")
        self.assertEqual(formal["evidence"][0]["clause"], [("part", "A")])

    def test_no_atom_lines_returns_none_and_explicit_none_is_empty(self):
        self.assertIsNone(parse_formalization("DECISION: CODE", TASK, "f"))
        formal = parse_formalization("ATOM none\nDECISION: CODE", TASK, "f")
        self.assertEqual(formal["atoms"], [])
        self.assertTrue(formal["explicit_none"])

    def test_invalid_check_expression_is_dropped(self):
        response = (
            'ATOM a | RULE | HIGH | default A | "not stated" | A: x | B: y\n'
            "CHECK a | A: result == ( | B: result is None\n"
        )
        atom = parse_formalization(response, TASK, "f")["atoms"][0]
        self.assertEqual(atom["check_A"], "")
        self.assertEqual(atom["check_B"], "result is None")

    def test_quote_in_text_is_case_and_punctuation_blind(self):
        self.assertTrue(quote_in_text("keep the ORIGINAL relative order.", TASK))
        self.assertFalse(quote_in_text("keep the order relative", TASK))

    def test_extract_examples_doctest_inline_and_boundaries(self):
        prompt = '''
def below_zero(operations: list) -> bool:
    """ Detect a negative balance.
    >>> below_zero([1, 2, 3])
    False
    >>> below_zero([1, 2, -4, 5])
    True
    not_below_zero([1]) == True
    below_zero([-1]) ➞ True (since it starts negative)
    below_zero(ops=[1]) == False
    """
'''
        examples = extract_examples(prompt, "below_zero")
        self.assertEqual(
            [(e["args"], e["expected"]) for e in examples],
            [(([1, 2, 3],), False), (([1, 2, -4, 5],), True), (([-1],), True)],
        )
        self.assertEqual(find_stub_params(prompt, "below_zero"), ["operations"])
        self.assertIsNone(find_stub_params("Write a function to add.", "add"))

    def test_atomic_question_keeps_only_the_first_question(self):
        self.assertEqual(
            atomic_question("Should it be strict? Also, what about empty input?"),
            "Should it be strict?",
        )
        self.assertEqual(
            atomic_question("Is zero positive. Additionally, is it sorted?"), "Is zero positive."
        )
        self.assertIsNone(atomic_question("Why?"))


# -------------------------------------------------------------------------------------------------
# plan(): pure decision logic
# -------------------------------------------------------------------------------------------------


def _atom(name, kind="VAGUE", impact="HIGH", phrase="", order=0, default="A"):
    return {
        "name": name,
        "kind": kind,
        "impact": impact,
        "default": default,
        "phrase": phrase,
        "A": f"{name} reading A",
        "B": f"{name} reading B",
        "check_A": "",
        "check_B": "",
        "order": order,
    }


def _ev(quote, *clause, source="text"):
    return {"quote": quote, "clause": list(clause), "source": source}


class PlanTest(unittest.TestCase):
    def test_contradiction_targets_the_core_and_quotes_both_sides(self):
        formal = {
            "atoms": [_atom("sig", kind="FORMAT", order=0), _atom("order", order=1)],
            "evidence": [
                _ev("keep the order", ("order", "A")),
                _ev("any order", ("order", "B")),
            ],
        }
        decision = plan(formal, [])
        self.assertEqual(decision["mode"], "contradiction")
        self.assertEqual(decision["target"]["name"], "order")  # not the first-listed atom
        self.assertEqual(decision["quotes"], ["keep the order", "any order"])
        question = build_question(decision, "f")
        self.assertIn('"keep the order" but also "any order"', question)
        self.assertEqual(question.count("?"), 1)

    def test_example_evidence_creates_a_contradiction_with_the_text(self):
        formal = {"atoms": [_atom("part")], "evidence": [_ev("decimal part", ("part", "A"))]}
        example = [_ev("truncate(3.5) == 3", ("part", "B"), source="example")]
        decision = plan(formal, example)
        self.assertEqual(decision["mode"], "contradiction")
        self.assertEqual(decision["quotes"], ["decimal part", "truncate(3.5) == 3"])

    def test_backbone_becomes_facts_and_free_high_atom_is_asked(self):
        formal = {
            "atoms": [
                _atom("edge", kind="EDGE", impact="LOW", order=0),
                _atom("fixed", kind="RULE", order=1),
                _atom("fmt", kind="FORMAT", order=2),
                _atom("vague", kind="VAGUE", order=3),
            ],
            "evidence": [_ev("always fixed", ("fixed", "B"))],
        }
        decision = plan(formal, [])
        self.assertEqual(decision["mode"], "ambiguity")
        self.assertEqual(decision["target"]["name"], "fmt")  # HIGH, then FORMAT before VAGUE
        self.assertEqual(decision["facts"], ["fixed reading B"])

    def test_implication_propagates_into_the_backbone(self):
        formal = {
            "atoms": [_atom("a", order=0), _atom("b", order=1)],
            "evidence": [_ev("if a then b", ("a", "B"), ("b", "A")), _ev("a holds", ("a", "A"))],
        }
        decision = plan(formal, [])
        self.assertEqual(decision["facts"], ["a reading A", "b reading A"])
        self.assertIsNone(decision["target"])

    def test_suspect_kinds_are_never_facts_and_stay_askable(self):
        formal = {
            "atoms": [_atom("odd", kind="ODD", order=0)],
            "evidence": [_ev("must return a string", ("odd", "A"))],
        }
        decision = plan(formal, [])
        self.assertEqual(decision["facts"], [])
        self.assertEqual(decision["target"]["name"], "odd")

    def test_contested_atoms_are_excluded_from_facts_but_others_remain(self):
        formal = {
            "atoms": [_atom("x", order=0), _atom("y", order=1)],
            "evidence": [
                _ev("x yes", ("x", "A")),
                _ev("x no", ("x", "B")),
                _ev("y yes", ("y", "A")),
            ],
        }
        decision = plan(formal, [])
        self.assertEqual(decision["target"]["name"], "x")
        self.assertEqual(decision["facts"], ["y reading A"])


# -------------------------------------------------------------------------------------------------
# run() end-to-end
# -------------------------------------------------------------------------------------------------

STUB_PROMPT = '''
def truncate_number(number: float) -> float:
    """ Return the decimal part of the number.
    >>> truncate_number(3.5)
    3
    """
'''
STUB_PROBLEM = {"prompt": STUB_PROMPT, "entry_point": "truncate_number"}
MBPP_PROBLEM = {
    "prompt": "Write a function to sum the items of an array.",
    "entry_point": "sum_arr",
}

TRUNC_CODE = "```python\ndef truncate_number(number):\n    return number % 1.0\n```"
SUM_CODE = "```python\ndef sum_arr(arr, n=None):\n    return sum(arr)\n```"

TRUNC_FORMAL_WITH_CHECKS = (
    'ATOM part | FORMAT | HIGH | default A | "Return the decimal part of the number" '
    "| A: the decimal part is returned | B: the integer part is returned\n"
    "CHECK part | A: abs(result - (number - int(number))) < 1e-9 | B: result == int(number)\n"
    'EVIDENCE "Return the decimal part of the number" => part=A\n'
    "DECISION: ASK\nQUESTION: Decimal or integer part?"
)


class _FakeEnv:
    def __init__(self, llm_responses, answer="Use the decimal part.", exec_mode="real", **kw):
        self.llm_responses = list(llm_responses)
        self.answer = answer
        self.exec_mode = exec_mode
        self.llm_exception_at = kw.get("llm_exception_at")
        self.llm_exception = kw.get("llm_exception")
        self.ask_exception = kw.get("ask_exception")
        self.prompts: list[str] = []
        self.questions: list[str] = []
        self.exec_calls = 0

    def llm(self, messages):
        content = messages if isinstance(messages, str) else messages[-1]["content"]
        self.prompts.append(content)
        if self.llm_exception_at is not None and len(self.prompts) - 1 == self.llm_exception_at:
            raise self.llm_exception
        return self.llm_responses.pop(0)

    def can_ask(self):
        return True

    def ask_human(self, query):
        self.questions.append(query)
        if self.ask_exception is not None:
            raise self.ask_exception
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
    def test_example_grounding_detects_text_vs_example_contradiction(self):
        env = _FakeEnv([TRUNC_FORMAL_WITH_CHECKS, TRUNC_CODE])
        result = LAASeR_FormalDPLL().run(env, STUB_PROBLEM)
        self.assertIn("def truncate_number", result)
        self.assertEqual(env.exec_calls, 1)
        self.assertEqual(len(env.questions), 1)
        question = env.questions[0]
        self.assertIn('"Return the decimal part of the number" but also', question)
        self.assertIn("truncate_number(3.5) == 3", question)
        self.assertNotIn("int(number)", question)  # checks never leak into questions
        self.assertIn("Answer: Use the decimal part.", env.prompts[-1])

    def test_a_single_failing_check_cannot_settle_an_atom(self):
        one_sided = TRUNC_FORMAL_WITH_CHECKS.replace("B: result == int(number)", "B: none")
        env = _FakeEnv([one_sided, TRUNC_CODE])
        LAASeR_FormalDPLL().run(env, STUB_PROBLEM)
        self.assertEqual((env.exec_calls, env.questions), (1, []))  # ran, but no example clause

    def test_grounding_failure_degrades_to_text_only_reasoning(self):
        # Without the sandbox the example's evidence is unavailable: the text alone settles the
        # atom, so it becomes a fact for the coder instead of a question -- and nothing crashes.
        env = _FakeEnv([TRUNC_FORMAL_WITH_CHECKS, TRUNC_CODE], exec_mode="raise")
        result = LAASeR_FormalDPLL().run(env, STUB_PROBLEM)
        self.assertIn("def truncate_number", result)
        self.assertEqual((env.exec_calls, env.questions), (1, []))
        self.assertIn("- the decimal part is returned", env.prompts[-1])

    def test_model_written_evidence_on_both_sides_is_a_contradiction_without_sandbox(self):
        formal = TRUNC_FORMAL_WITH_CHECKS.replace(
            "DECISION:", 'EVIDENCE "truncate_number(3.5)" => part=B\nDECISION:'
        )
        env = _FakeEnv([formal, TRUNC_CODE], exec_mode="raise")
        LAASeR_FormalDPLL().run(env, STUB_PROBLEM)
        self.assertEqual(len(env.questions), 1)
        self.assertIn('but also "truncate_number(3.5)"', env.questions[0])

    def test_no_atoms_and_code_decision_uses_one_llm_call(self):
        env = _FakeEnv(["ATOM none\nDECISION: CODE\n" + TRUNC_CODE])
        result = LAASeR_FormalDPLL().run(env, STUB_PROBLEM)
        self.assertIn("def truncate_number", result)
        self.assertEqual((len(env.prompts), env.questions, env.exec_calls), (1, [], 0))

    def test_low_impact_only_with_stub_codes_without_asking(self):
        formal = (
            'ATOM neg | EDGE | LOW | default A | "not stated" | A: works on negatives '
            "| B: rejects negatives\nDECISION: CODE\n" + TRUNC_CODE
        )
        env = _FakeEnv([formal])
        LAASeR_FormalDPLL().run(env, STUB_PROBLEM)
        self.assertEqual(env.questions, [])

    def test_without_stub_hedge_rule_is_added_and_low_atoms_are_asked(self):
        formal = (
            'ATOM empty | EDGE | LOW | default A | "not stated" | A: an empty array sums to 0 '
            "| B: an empty array raises an error\nDECISION: CODE\n" + SUM_CODE
        )
        env = _FakeEnv([formal, SUM_CODE], answer="It returns 0.")
        result = LAASeR_FormalDPLL().run(env, MBPP_PROBLEM)
        self.assertIn("def sum_arr", result)
        self.assertIn("optional last parameter", env.prompts[0])
        self.assertIn("never make an atom for it", env.prompts[0])
        self.assertEqual(len(env.questions), 1)
        self.assertIn("does not settle this for `sum_arr`", env.questions[0])

    def test_hedge_can_be_disabled_by_config(self):
        env = _FakeEnv(["ATOM none\nDECISION: CODE\n" + SUM_CODE])
        LAASeR_FormalDPLL({"signature_hedge": False}).run(env, MBPP_PROBLEM)
        self.assertNotIn("optional last parameter", env.prompts[0])

    def test_unparseable_formalization_falls_back_to_models_atomic_question(self):
        env = _FakeEnv(
            ["DECISION: ASK\nQUESTION: Is zero positive? Also, is the input sorted?", SUM_CODE]
        )
        LAASeR_FormalDPLL().run(env, MBPP_PROBLEM)
        self.assertEqual(env.questions, ["Is zero positive?"])

    def test_facts_block_reaches_the_coder(self):
        formal = (
            'ATOM total | RULE | HIGH | default A | "sum the items" | A: the plain sum is returned '
            "| B: the sum of absolute values is returned\n"
            'ATOM empty | EDGE | HIGH | default A | "not stated" | A: empty gives 0 | B: empty gives None\n'
            'EVIDENCE "sum the items of an array" => total=A\n'
            "DECISION: ASK\nQUESTION: What about empty input?"
        )
        env = _FakeEnv([formal, SUM_CODE], answer="Return 0.")
        LAASeR_FormalDPLL().run(env, MBPP_PROBLEM)
        self.assertEqual(len(env.questions), 1)
        self.assertIn("empty gives 0, or empty gives None", env.questions[0])
        self.assertIn("- the plain sum is returned", env.prompts[-1])

    def test_too_many_questions_still_codes(self):
        env = _FakeEnv(
            [TRUNC_FORMAL_WITH_CHECKS, TRUNC_CODE], ask_exception=TooManyQuestionException()
        )
        self.assertIn("def truncate_number", LAASeR_FormalDPLL().run(env, STUB_PROBLEM))

    def test_budget_exhausted_on_first_call_returns_empty(self):
        env = _FakeEnv([], llm_exception_at=0, llm_exception=LimitsExceededException())
        self.assertEqual(LAASeR_FormalDPLL().run(env, STUB_PROBLEM), "")

    def test_unexpected_error_triggers_one_plain_coding_attempt(self):
        env = _FakeEnv([TRUNC_CODE], llm_exception_at=0, llm_exception=RuntimeError("boom"))
        result = LAASeR_FormalDPLL().run(env, STUB_PROBLEM)
        self.assertIn("def truncate_number", result)

    def test_wrong_name_is_repaired(self):
        wrong = "```python\ndef trunc(number):\n    return number % 1.0\n```"
        env = _FakeEnv([TRUNC_FORMAL_WITH_CHECKS, wrong, TRUNC_CODE])
        result = LAASeR_FormalDPLL().run(env, STUB_PROBLEM)
        self.assertIn("def truncate_number", result)


if __name__ == "__main__":
    unittest.main()
