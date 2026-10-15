"""Tests for the determinism options of clarify/algorithms/laaser_pinpoint_smt_3.py:
`decision_votes` (ASK/CODE by majority of sampled audits) and `question_choice="consensus"`
(the question most audits agree on, chosen without another sampled call).

Offline, no network/Docker: the LLM replies are scripted.
"""

from __future__ import annotations

import itertools
import unittest

from clarify.algorithms.laaser_pinpoint_smt_3 import (
    LAASeR_PinpointSMT,
    consensus_question,
    majority_decision,
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


if __name__ == "__main__":
    unittest.main()
