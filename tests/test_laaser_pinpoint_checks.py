"""Tests for clarify/algorithms/laaser_pinpoint_checks.py: preclean, checks from the stated
examples and the user's answer, selection and repair. Offline: LLM replies are scripted."""

from __future__ import annotations

import unittest

from test_laaser_pinpoint_smt_3 import _FakeEnv

from clarify.algorithms.laaser_pinpoint_checks import (
    LAASeR_PinpointChecks,
    accept_cleanup,
    parse_checks,
)

TASK = (
    "Write a function to return the sum of a list. The result must be returned as a string.\n"
    "assert total([1, 2, 3]) == 6\n"
)
CLEANED = "Write a function to return the sum of a list.\nassert total([1, 2, 3]) == 6\n"
WRONG = "```python\ndef total(xs):\n    return str(sum(xs))\n```"
RIGHT = "```python\ndef total(xs):\n    return sum(xs)\n```"


class AcceptCleanupTest(unittest.TestCase):
    def test_a_pure_deletion_is_kept(self):
        self.assertEqual(accept_cleanup(TASK, CLEANED, "total"), CLEANED)

    def test_an_edited_example_is_rejected(self):
        edited = CLEANED.replace("== 6", "== 7")
        self.assertIsNone(accept_cleanup(TASK, edited, "total"))

    def test_added_words_are_rejected(self):
        self.assertIsNone(accept_cleanup(TASK, CLEANED + "Return an integer.\n", "total"))


class ParseChecksTest(unittest.TestCase):
    EXAMPLES = [("total([1, 2, 3])", ([1, 2, 3],), 6), ("total([])", ([],), 1)]

    def test_dropped_examples_go_and_confirmed_calls_come(self):
        reply = "EXAMPLE 1: KEEP\nEXAMPLE 2: DROP\ntotal([4]) == 4\n"
        checks = parse_checks(reply, "total", self.EXAMPLES)
        self.assertEqual([c[0] for c in checks], ["total([1, 2, 3])", "total([4])"])


def algo(**config):
    return LAASeR_PinpointChecks(
        {
            "verify": False,
            "checklist": False,
            "question_samples": 1,
            "candidates": 1,
            "format_question": False,
            **config,
        }
    )


class SelectionTest(unittest.TestCase):
    def test_the_implementation_passing_the_checks_wins(self):
        audit = (
            "STEP 1 - DEFECTS\n- none\nSTEP 2 - DECISION\nDECISION: ASK\n"
            "QUESTION: Should total return an integer or a string?\n"
        )
        env = _FakeEnv(
            [
                "```text\n" + CLEANED + "```",  # preclean
                audit,
                WRONG,  # v7's code
                "EXAMPLE 1: KEEP\n",  # checks
                RIGHT,  # final 1
                WRONG,  # final 2
            ],
            answer="An integer.",
        )
        code = algo().run(env, {"prompt": TASK, "entry_point": "total"})
        self.assertIn("return sum(xs)", code)
        self.assertNotIn("str(", code)
        self.assertNotIn("as a string", env.prompts[1])  # our steps read the cleaned task

    def test_a_repair_that_passes_more_checks_is_kept(self):
        prompt = "Sum a list.\nassert total([1, 2, 3]) == 6\nassert total([]) == 0\n"
        first = "def total(xs):\n    return sum(xs) if xs else 1\n"
        other = "```python\ndef total(xs):\n    return 0 if not xs else 99\n```"
        env = _FakeEnv([other, RIGHT])
        problem = {"prompt": prompt, "entry_point": "total"}
        code = algo(finals=1).check_and_select(env, problem, first, "", False, "")
        self.assertIn("return sum(xs)\n", code)
        self.assertIn("fails some checks", env.prompts[-1])
        self.assertIn("total([]) should return 0", env.prompts[-1])


if __name__ == "__main__":
    unittest.main()
