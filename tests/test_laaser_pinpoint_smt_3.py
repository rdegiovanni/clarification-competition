"""Tests for the options of clarify/algorithms/laaser_pinpoint_smt_3.py added on top of v7:
`decision_votes` (ASK/CODE by majority of sampled audits), `question_choice="consensus"`
(the question most audits agree on, chosen without another sampled call) and `spec_rewrite`
(code from the task rewritten with the user's answer folded in) and `resolve_defects` (explicit,
voted decisions on the audit's other defects, with z3 checking readings against the examples).

Offline, no network/Docker: the LLM replies are scripted.
"""

from __future__ import annotations

import itertools
import subprocess
import sys
import unittest

from clarify.algorithms import laaser_pinpoint_smt_3
from clarify.algorithms.laaser_pinpoint_smt_3 import (
    LAASeR_PinpointSMT,
    consensus_question,
    divergent_call,
    example_verdicts,
    majority_decision,
    parse_points,
    resolve_by_convention,
    resolve_defects,
    rewrite_spec,
    shows_signature,
    vote_points,
    witness_question,
)

TASK = {
    "prompt": "Write a function to count the elements of a list that are greater than k.",
    "entry_point": "count_greater",
}
STRICT = 'The task says "greater than" - should elements equal to k be excluded, or counted?'
STRICT_2 = 'The task says "greater than": should elements equal to k be excluded or counted?'
EMPTY = "What should count_greater return for an empty list?"


def ask(question: str) -> str:
    return f"STEP 1 - DEFECTS\n- none\nSTEP 2 - DECISION\nDECISION: ASK\nQUESTION: {question}\n"


CODE_AUDIT = (
    "STEP 1 - DEFECTS\n- none\nSTEP 2 - DECISION\nDECISION: CODE\n"
    "```python\ndef count_greater(arr, k):\n    return sum(1 for x in arr if x > k)\n```\n"
)
CODE_REPLY = (
    "```python\ndef count_greater(arr, k):\n    return sum(1 for x in arr if x >= k)\n```\n"
)


class _FakeEnv:
    def __init__(self, replies, answer="Counted."):
        self.replies = list(replies)
        self.answer = answer
        self.prompts: list[str] = []
        self.questions: list[str] = []

    def llm(self, messages):
        self.prompts.append(messages if isinstance(messages, str) else messages[-1]["content"])
        return self.replies.pop(0)

    def can_ask(self):
        return True

    def ask_human(self, query):
        self.questions.append(query)
        return self.answer

    def exec_code(self, script):
        done = subprocess.run(
            [sys.executable, "-I", "-c", script], capture_output=True, text=True, timeout=60
        )
        return done.stdout + done.stderr


def _algo(**config):
    return LAASeR_PinpointSMT(
        {
            "verify": False,
            "tolerate_extra_args": False,
            "checklist": False,
            "question_samples": 1,
            "candidates": 1,
            **config,
        }
    )


class ConsensusQuestionTest(unittest.TestCase):
    def test_the_majority_reading_wins(self):
        self.assertIn(consensus_question([EMPTY, STRICT, STRICT_2]), (1, 2))

    def test_the_choice_does_not_depend_on_the_order_of_the_samples(self):
        questions = [EMPTY, STRICT, STRICT_2]
        chosen = {
            questions_order[consensus_question(list(questions_order))]
            for questions_order in itertools.permutations(questions)
        }
        self.assertEqual(len(chosen), 1)

    def test_duplicates_are_votes(self):
        self.assertEqual(
            [EMPTY, STRICT, STRICT][consensus_question([EMPTY, STRICT, STRICT])], STRICT
        )

    def test_a_single_question_is_kept(self):
        self.assertEqual(consensus_question([EMPTY]), 0)


class MajorityDecisionTest(unittest.TestCase):
    def test_majority(self):
        self.assertEqual(majority_decision(["CODE", "ASK", "CODE"]), "CODE")
        self.assertEqual(majority_decision(["ASK", "ASK", "CODE"]), "ASK")

    def test_a_tie_asks(self):
        self.assertEqual(majority_decision(["CODE", "ASK", None]), "ASK")

    def test_undecided_audits_do_not_vote(self):
        self.assertEqual(majority_decision([None, None, "CODE"]), "CODE")
        self.assertIsNone(majority_decision([None, None]))


class VotedRunTest(unittest.TestCase):
    def test_default_config_is_v7(self):
        defaults = LAASeR_PinpointSMT.DEFAULT_CONFIG
        self.assertEqual(defaults["decision_votes"], 1)
        self.assertEqual(defaults["question_choice"], "judge")

    def test_one_asking_audit_is_outvoted_by_two_coding_ones(self):
        env = _FakeEnv([ask(STRICT), CODE_AUDIT, CODE_AUDIT])
        result = _algo(decision_votes=3, question_choice="consensus").run(env, TASK)
        self.assertEqual(env.questions, [])
        self.assertIn("x > k", result)
        self.assertEqual(len(env.prompts), 3)  # three audits, no judge, no coding call

    def test_the_majority_asks_the_consensus_question_without_a_judge(self):
        env = _FakeEnv([ask(EMPTY), ask(STRICT), CODE_AUDIT, ask(STRICT_2), CODE_REPLY])
        result = _algo(decision_votes=4, question_choice="consensus").run(env, TASK)
        self.assertEqual(len(env.questions), 1)
        self.assertIn("greater than", env.questions[0])
        self.assertIn("x >= k", result)
        self.assertEqual(len(env.prompts), 5)  # four audits and the coding call

    def test_voted_audits_with_the_judge(self):
        judge = "1: PASS\n2: FAIL\nBEST: 1"
        env = _FakeEnv([ask(EMPTY), ask(STRICT), CODE_AUDIT, judge, CODE_REPLY])
        _algo(decision_votes=3).run(env, TASK)
        self.assertEqual(env.questions, [EMPTY])

    def test_samples_without_votes_use_the_consensus_too(self):
        env = _FakeEnv([ask(EMPTY), ask(STRICT), ask(STRICT_2), CODE_REPLY])
        _algo(question_samples=3, question_choice="consensus").run(env, TASK)
        self.assertIn("greater than", env.questions[0])
        self.assertEqual(len(env.prompts), 4)  # no judge call


STUB = {
    "prompt": (
        "def count_greater(arr, k):\n"
        '    """Count the elements of arr that are greater than k.\n'
        "    >>> count_greater([1, 5, 7], 5)\n"
        "    1\n"
        '    """\n'
    ),
    "entry_point": "count_greater",
}
SPEC = (
    "def count_greater(arr, k):\n"
    '    """Count the elements of arr that are greater than or equal to k.\n'
    "    >>> count_greater([1, 5, 7], 5)\n"
    "    2\n"
    '    """\n'
)


def spec_reply(spec: str) -> str:
    return f"SPEC_START\n{spec}\nSPEC_END\n"


class SpecRewriteTest(unittest.TestCase):
    def test_the_rewrite_is_kept_when_it_keeps_the_signature(self):
        env = _FakeEnv([spec_reply(SPEC)])
        self.assertEqual(rewrite_spec(env, STUB, STRICT, "Counted."), SPEC.strip("\n"))
        self.assertIn("signature exactly as written: def count_greater(arr, k):", env.prompts[0])

    def test_a_rewrite_that_changes_the_signature_is_dropped(self):
        env = _FakeEnv([spec_reply(SPEC.replace("(arr, k)", "(numbers, k)"))])
        self.assertIsNone(rewrite_spec(env, STUB, STRICT, "Counted."))

    def test_a_rewrite_without_markers_or_entry_point_is_dropped(self):
        self.assertIsNone(rewrite_spec(_FakeEnv(["Here it is: ..."]), TASK, STRICT, "Counted."))
        self.assertIsNone(
            rewrite_spec(_FakeEnv([spec_reply("Count big things.")]), TASK, STRICT, "Counted.")
        )

    def test_the_code_is_written_from_the_rewritten_task(self):
        env = _FakeEnv([ask(STRICT), spec_reply(SPEC), CODE_REPLY])
        result = _algo(spec_rewrite=True).run(env, STUB)
        self.assertIn("x >= k", result)
        self.assertIn("greater than or equal to k", env.prompts[2])  # the coding prompt
        self.assertIn("Answer: Counted.", env.prompts[2])  # the answer stays attached

    def test_an_unusable_rewrite_falls_back_to_the_task(self):
        env = _FakeEnv([ask(STRICT), "no markers", CODE_REPLY])
        _algo(spec_rewrite=True).run(env, STUB)
        self.assertIn("greater than k.", env.prompts[2])

    def test_no_rewrite_without_a_real_answer(self):
        env = _FakeEnv([ask(STRICT), CODE_REPLY], answer="Please ask one question at a time.")
        _algo(spec_rewrite=True).run(env, STUB)
        self.assertEqual(len(env.prompts), 2)  # audit and code, no rewrite call

    def test_off_by_default(self):
        self.assertFalse(LAASeR_PinpointSMT.DEFAULT_CONFIG["spec_rewrite"])
        env = _FakeEnv([ask(STRICT), CODE_REPLY])
        _algo().run(env, STUB)
        self.assertEqual(len(env.prompts), 2)


HAS_Z3 = laaser_pinpoint_smt_3.z3 is not None
PLUS_ONE = "(define-fun f ((x Int)) Int (+ x 1))"
TWICE = "(define-fun f ((x Int)) Int (* x 2))"
AMBIGUITY = {"quote": "grow", "A": "add one", "B": "double", "def_A": PLUS_ONE, "def_B": TWICE}
TWO_DEFECTS = (
    "STEP 1 - DEFECTS\n"
    '- VAGUE | "greater than" | reading A: strictly | reading B: or equal | IMPACT: HIGH\n'
    '- MISSING | "not stated" | reading A: [] gives 0 | reading B: [] raises | IMPACT: HIGH\n'
    "STEP 2 - DECISION\nDECISION: ASK\n"
)


class ExampleVerdictTest(unittest.TestCase):
    @unittest.skipUnless(HAS_Z3, "z3-solver not installed")
    def test_z3_evaluates_both_readings_on_the_examples(self):
        examples = [{"args": (3,), "expected": 4}, {"args": (0,), "expected": 1}]
        (verdict,) = example_verdicts([], [AMBIGUITY], examples)
        self.assertEqual(verdict["fits_A"], (2, 2))
        self.assertEqual(verdict["fits_B"], (0, 2))

    @unittest.skipUnless(HAS_Z3, "z3-solver not installed")
    def test_examples_that_do_not_fit_the_sorts_are_skipped(self):
        self.assertEqual(example_verdicts([], [AMBIGUITY], [{"args": ("a",), "expected": 1}]), [])

    def test_nothing_without_examples(self):
        self.assertEqual(example_verdicts([], [AMBIGUITY], []), [])


class ResolveTest(unittest.TestCase):
    def test_points_are_parsed_leniently(self):
        reply = (
            "POINT 1: A | ANSWER | count only elements strictly greater than k\n"
            "**POINT 2: B** | Examples | raise ValueError on an empty list\n"
            "POINT 9: A | CONVENTION | out of range\n"
        )
        points = parse_points(reply, 2)
        self.assertEqual(points[0][0], "A")
        self.assertEqual(points[1], ("B", "EXAMPLE", "raise ValueError on an empty list"))
        self.assertNotIn(8, points)

    def test_only_strict_majorities_are_kept(self):
        a = {0: ("A", "ANSWER", "strict"), 1: ("A", "CONVENTION", "zero for empty")}
        b = {0: ("A", "ANSWER", "strict!"), 1: ("B", "CONVENTION", "raise for empty")}
        self.assertEqual(vote_points([a, b, a], 2), ["- strict", "- zero for empty"])
        self.assertEqual(vote_points([a, b], 2), ["- strict"])  # 1-1 on point 2: undecided

    def test_drop_becomes_an_instruction_to_ignore(self):
        self.assertEqual(
            vote_points([{0: ("DROP", "CONVENTION", "the O(1) rule")}], 1),
            ["- Ignore: the O(1) rule"],
        )

    def test_resolve_votes_over_samples(self):
        reply = "POINT 1: A | ANSWER | strict\nPOINT 2: A | CONVENTION | return 0 for []\n"
        env = _FakeEnv([reply, reply, reply])
        block = resolve_defects(env, TASK, TWO_DEFECTS, STRICT, "Counted.", 3)
        self.assertIn("- return 0 for []", block)
        self.assertEqual(len(env.prompts), 3)  # no examples: no formalization call

    def test_a_single_defect_needs_no_resolution(self):
        env = _FakeEnv([])
        self.assertEqual(resolve_defects(env, TASK, ask(STRICT), STRICT, "Counted.", 3), "")
        self.assertEqual(env.prompts, [])

    def test_decisions_reach_the_coder_and_the_spec(self):
        reply = "POINT 1: A | ANSWER | strict\nPOINT 2: A | CONVENTION | return 0 for []\n"
        audit = TWO_DEFECTS + f"QUESTION: {STRICT}\n"
        readings = ["no formalization"] if HAS_Z3 else []  # STUB has an example
        env = _FakeEnv([audit, *readings, reply, spec_reply(SPEC), CODE_REPLY])
        _algo(resolve_defects=True, resolve_votes=1, spec_rewrite=True).run(env, STUB)
        rewrite, code = env.prompts[-2], env.prompts[-1]
        self.assertIn("SPEC_START", rewrite)
        self.assertIn("return 0 for []", rewrite)  # the rewrite sees the decisions
        self.assertIn("return 0 for []", code)  # and so does the coder

    def test_off_by_default(self):
        self.assertFalse(LAASeR_PinpointSMT.DEFAULT_CONFIG["resolve_defects"])


def code(body: str) -> str:
    return f"```python\ndef count_greater(arr, k):\n    return {body}\n```\n"


STRICT_CODE, LOOSE_CODE = (
    code("sum(1 for x in arr if x > k)"),
    code("sum(1 for x in arr if x >= k)"),
)
PROBES = "CALL count_greater([1, 9], 5)\ncount_greater([7], 7)\n"
READINGS = 'PHRASE: "greater than"\nREADING 1: only elements strictly greater\nREADING 2: elements greater or equal\n'
WITNESS_Q = (
    'The task says "greater than". For example, should count_greater([7], 7) return 0 '
    "(only elements strictly greater) or 1 (elements greater or equal)?"
)


def report(*values):
    return {"load_error": None, "results": [("VALUE", v) for v in values]}


class DivergenceTest(unittest.TestCase):
    def test_the_most_evenly_split_call_is_chosen(self):
        reports = [report("1", "0"), report("1", "1"), report("1", "0"), report("2", "1")]
        index, shown = divergent_call(reports, 2)
        self.assertEqual(index, 1)  # 2-2 split beats 3-1
        self.assertEqual(shown, [("0", 2), ("1", 2)])

    def test_agreement_and_crashes_are_not_divergence(self):
        crash = {"load_error": None, "results": [("EXC", "ZeroDivisionError: x"), ("VALUE", "1")]}
        self.assertIsNone(divergent_call([report("1", "1"), report("1", "1"), crash], 2))
        self.assertIsNone(
            divergent_call([None, {"load_error": ("SyntaxError", ""), "results": []}], 1)
        )

    def test_the_question_targets_the_witness(self):
        replies = [ask(EMPTY), STRICT_CODE, LOOSE_CODE, STRICT_CODE, LOOSE_CODE, PROBES]
        env = _FakeEnv([*replies, READINGS, LOOSE_CODE])
        result = _algo(question_target="divergence").run(env, TASK)
        self.assertEqual(env.questions, [WITNESS_Q])  # assembled around the witness
        self.assertIn("count_greater([7], 7)", env.prompts[6])
        self.assertIn("RESULT 1: 0", env.prompts[6])
        self.assertIn("x >= k", result)

    def test_the_witness_question_survives_a_sloppy_reply(self):
        question = witness_question("no format at all", TASK["prompt"], "f([7], 7)", "0", "1")
        self.assertEqual(question, "For example, should f([7], 7) return 0 or 1?")
        invented = 'PHRASE: "a phrase the task never says"\nREADING 1: a\nREADING 2: b'
        question = witness_question(invented, TASK["prompt"], "f(1)", "'00'", "'0'")
        self.assertEqual(question, "For example, should f(1) return '00' (a) or '0' (b)?")

    def test_without_a_split_the_audit_question_stands(self):
        replies = [ask(EMPTY), STRICT_CODE, STRICT_CODE, STRICT_CODE, STRICT_CODE, PROBES]
        env = _FakeEnv([*replies, STRICT_CODE])
        _algo(question_target="divergence").run(env, TASK)
        self.assertEqual(env.questions, [EMPTY])
        self.assertEqual(len(env.prompts), 7)  # no question-writing call

    def test_a_coding_audit_samples_nothing(self):
        env = _FakeEnv([CODE_AUDIT])
        _algo(question_target="divergence").run(env, TASK)
        self.assertEqual(len(env.prompts), 1)

    def test_off_by_default(self):
        self.assertEqual(LAASeR_PinpointSMT.DEFAULT_CONFIG["question_target"], "audit")


CONVENTION_REPLY = (
    "POINT 1: ANSWER | count elements equal to k too\n"
    "POINT 2: DROP | the extra sum returned alongside the result\n"
)


class ConventionResolveTest(unittest.TestCase):
    def test_answer_and_drop_points_are_kept_open_ones_are_not(self):
        reply = CONVENTION_REPLY + "POINT 3: OPEN | whatever\n"
        audit = TWO_DEFECTS.replace(
            "STEP 2", '- MISSING | "not stated" | reading A: x | reading B: y | IMPACT: LOW\nSTEP 2'
        )
        block = resolve_by_convention(_FakeEnv([reply] * 3), TASK, audit, STRICT, "Counted.", 3)
        self.assertIn("- count elements equal to k too", block)
        self.assertIn("- Ignore: the extra sum returned alongside the result", block)
        self.assertNotIn("whatever", block)

    def test_only_strict_majorities(self):
        other = "POINT 1: OPEN | -\nPOINT 2: OPEN | -\n"
        env = _FakeEnv([CONVENTION_REPLY, other])
        self.assertEqual(resolve_by_convention(env, TASK, TWO_DEFECTS, STRICT, "Counted.", 2), "")

    def test_the_examples_are_never_formalized(self):
        audit = TWO_DEFECTS + f"QUESTION: {STRICT}\n"
        env = _FakeEnv([audit, CONVENTION_REPLY, CODE_REPLY])  # STUB has an example
        _algo(resolve_defects=True, resolve_mode="convention", resolve_votes=1).run(env, STUB)
        self.assertEqual(len(env.prompts), 3)  # audit, convention, code: no READINGS call
        self.assertIn("Ignore: the extra sum", env.prompts[2])
        self.assertIn("never use the examples", env.prompts[1])

    def test_full_mode_is_the_default(self):
        self.assertEqual(LAASeR_PinpointSMT.DEFAULT_CONFIG["resolve_mode"], "full")


CODING_WITH_DEFECTS = (
    "STEP 1 - DEFECTS\n"
    '- VAGUE | "greater than" | reading A: strictly | reading B: or equal | IMPACT: LOW\n'
    "STEP 2 - DECISION\nDECISION: CODE\n"
    "```python\ndef count_greater(arr, k):\n    return sum(1 for x in arr if x > k)\n```\n"
)


class SubmissionFlagsTest(unittest.TestCase):
    def test_without_the_solver_no_formalization_call_is_made(self):
        env = _FakeEnv([CODING_WITH_DEFECTS])
        _algo(use_solver=False).run(env, TASK)
        self.assertEqual(len(env.prompts), 1)  # only the audit
        self.assertEqual(env.questions, [])

    @unittest.skipUnless(HAS_Z3, "z3-solver not installed")
    def test_with_the_solver_the_readings_are_formalized(self):
        env = _FakeEnv([CODING_WITH_DEFECTS, "no formalization"])
        _algo().run(env, TASK)
        self.assertIn("SMT-LIB", env.prompts[1])

    def test_priority_reaches_the_judge_only_when_on(self):
        judge = "1: PASS\n2: PASS\nBEST: 2"
        for priority in (False, True):
            env = _FakeEnv([ask(EMPTY), ask(STRICT), judge, CODE_REPLY])
            _algo(question_samples=2, question_priority=priority).run(env, TASK)
            self.assertEqual(env.questions, [STRICT])
            self.assertEqual("order of value" in env.prompts[2], priority)

    def test_defaults(self):
        defaults = LAASeR_PinpointSMT.DEFAULT_CONFIG
        self.assertTrue(defaults["use_solver"])
        self.assertFalse(defaults["question_priority"])


class StubProfileTest(unittest.TestCase):
    def test_signature_detection(self):
        self.assertTrue(shows_signature(STUB))
        self.assertFalse(shows_signature(TASK))  # prose: "Write a function ..."

    def test_a_stub_task_runs_like_pinpoint(self):
        env = _FakeEnv([ask(STRICT), CODE_REPLY])  # one audit, no judge, no checklist
        result = _algo(question_samples=3, checklist=True, stub_profile="pinpoint").run(env, STUB)
        self.assertIn("x >= k", result)
        self.assertEqual(len(env.prompts), 2)
        self.assertNotIn("SHAPE REFERENCE", env.prompts[0])

    def test_a_prose_task_keeps_the_full_configuration(self):
        env = _FakeEnv([ask(EMPTY), ask(STRICT), "1: PASS\n2: PASS\nBEST: 1", CODE_REPLY])
        _algo(question_samples=2, stub_profile="pinpoint").run(env, TASK)
        self.assertEqual(len(env.prompts), 4)  # two audits and the judge, as configured

    def test_same_is_the_default(self):
        self.assertEqual(LAASeR_PinpointSMT.DEFAULT_CONFIG["stub_profile"], "same")


class ArgumentConventionTest(unittest.TestCase):
    def test_prose_tasks_get_the_rule_in_the_audit_and_the_coding_prompt(self):
        env = _FakeEnv([ask(STRICT), CODE_REPLY])
        _algo(argument_convention=True).run(env, TASK)
        self.assertIn("collection being", env.prompts[0])
        self.assertIn("collection being", env.prompts[1])

    def test_tasks_that_show_the_signature_do_not(self):
        env = _FakeEnv([ask(STRICT), CODE_REPLY])
        _algo(argument_convention=True).run(env, STUB)
        self.assertNotIn("collection being", env.prompts[0] + env.prompts[1])

    def test_off_by_default(self):
        env = _FakeEnv([ask(STRICT), CODE_REPLY])
        _algo().run(env, TASK)
        self.assertNotIn("collection being", env.prompts[0] + env.prompts[1])


if __name__ == "__main__":
    unittest.main()
