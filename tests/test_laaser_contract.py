"""Tests for clarify/algorithms/laaser_contract.py (the submission file).

Offline, no network/Docker: LLM replies are scripted. Besides each step, the file is checked
against the development file it was reorganized from (laaser_pinpoint_smt_3.py with the
submission candidate's flags): on the same replies both must make the same LLM calls, ask the
same question and return the same code.
"""

from __future__ import annotations

import time
import unittest

from test_laaser_pinpoint_smt_3 import CODE_AUDIT, CODE_REPLY, STRICT, TASK, _FakeEnv, ask

from clarify.algorithms import laaser_contract
from clarify.algorithms.laaser_contract import LAASeR_Contract, call_adapter
from clarify.algorithms.laaser_pinpoint_smt_3 import LAASeR_PinpointSMT

CONTRACT = (
    "QUESTION: I will assume count_greater takes a list of integers first and an integer k"
    " second and returns the integer count of elements strictly greater than k, e.g."
    " count_greater([1, 5, 7], 5) returns 1. Is that right, or should elements equal to k count?"
)
OFFLINE = {"verify": False, "use_solver": False}
CANDIDATE_FLAGS = {
    "reorder_arguments": True,
    "format_question": "dedicated",
    "contract_question": True,
    "contract_always": True,
    "contract_evidence": "solver",
    "contract_order": True,
    "call_adapter": True,
}


def contract_prompt(env):
    return next(p for p in env.prompts if "Draft:" in p)


class PipelineTest(unittest.TestCase):
    def test_one_contract_question_then_code(self):
        env = _FakeEnv([ask(STRICT), CODE_REPLY, CONTRACT, CODE_REPLY])
        code = LAASeR_Contract(OFFLINE).run(env, TASK)
        self.assertEqual(len(env.questions), 1)
        self.assertTrue(env.questions[0].startswith("I will assume count_greater"))
        self.assertIn("def count_greater", code)
        self.assertEqual(env.replies, [])  # no sampled audits, no judge

    def test_the_contract_is_asked_even_when_the_audit_would_code(self):
        env = _FakeEnv([CODE_AUDIT, CODE_REPLY, CONTRACT, CODE_REPLY])
        LAASeR_Contract(OFFLINE).run(env, TASK)
        self.assertEqual(len(env.questions), 1)

    def test_without_a_draft_the_sampled_audit_question_is_asked(self):
        env = _FakeEnv([ask(STRICT), "no code", ask(STRICT), ask(STRICT), CODE_REPLY])
        LAASeR_Contract(OFFLINE).run(env, TASK)
        self.assertEqual(env.questions, [STRICT])

    def test_the_argument_order_is_requested_only_without_a_signature(self):
        env = _FakeEnv([ask(STRICT), CODE_REPLY, CONTRACT, CODE_REPLY])
        LAASeR_Contract(OFFLINE).run(env, TASK)
        self.assertIn("first argument> first", contract_prompt(env))
        stub = {**TASK, "prompt": 'def count_greater(arr, k):\n    """Count > k."""\n'}
        env = _FakeEnv([ask(STRICT), CODE_REPLY, CONTRACT, CODE_REPLY])
        LAASeR_Contract(OFFLINE).run(env, stub)
        self.assertNotIn("first argument> first", contract_prompt(env))

    def test_a_proven_conflict_reaches_the_contract_question(self):
        proven = {"question": 'The task says "x", but the example "f(1) == 2" does not hold.'}
        original = laaser_contract.find_certificate
        laaser_contract.find_certificate = lambda *args, **kwargs: proven
        try:
            env = _FakeEnv([ask(STRICT), CODE_REPLY, CONTRACT, CODE_REPLY])
            LAASeR_Contract(OFFLINE).run(env, TASK)
        finally:
            laaser_contract.find_certificate = original
        self.assertIn("Proven with a solver", contract_prompt(env))
        self.assertIn('the example "f(1) == 2"', contract_prompt(env))

    def test_drafts_run_before_the_question(self):
        task = {**TASK, "prompt": TASK["prompt"] + "\n>>> count_greater([1, 5, 7], 5)\n1\n"}
        strict = "```python\ndef count_greater(arr, k):\n    return sum(x > k for x in arr)\n```"
        probes = "CALL count_greater([2, 2, 3], 2)\n"
        env = _FakeEnv([ask(STRICT), CODE_REPLY, strict, CODE_REPLY, probes, CONTRACT, CODE_REPLY])
        LAASeR_Contract({**OFFLINE, "contract_drafts": 3}).run(env, task)
        self.assertIn("x > k", contract_prompt(env))
        self.assertIn("the drafts disagree on count_greater([2, 2, 3], 2)", contract_prompt(env))

    def test_the_returned_code_tolerates_a_redundant_length(self):
        env = _FakeEnv([ask(STRICT), CODE_REPLY, CONTRACT, CODE_REPLY])
        code = LAASeR_Contract(OFFLINE).run(env, TASK)
        namespace = {}
        exec(code, namespace)
        self.assertEqual(namespace["count_greater"]([1, 5, 7], 3, 5), 2)


class SameAsDevelopmentFileTest(unittest.TestCase):
    """The submission file behaves as laaser_pinpoint_smt_3.py with the candidate's flags."""

    def compare(self, replies, task, answer="Counted."):
        new_env, dev_env = _FakeEnv(list(replies), answer), _FakeEnv(list(replies), answer)
        new = LAASeR_Contract({**OFFLINE, "question_samples": 3}).run(new_env, task)
        dev = LAASeR_PinpointSMT({**CANDIDATE_FLAGS, **OFFLINE}).run(dev_env, task)
        self.assertEqual(new_env.prompts, dev_env.prompts)
        self.assertEqual(new_env.questions, dev_env.questions)
        self.assertEqual(new, dev)

    def test_prose_task(self):
        self.compare([ask(STRICT), CODE_REPLY, CONTRACT, CODE_REPLY], TASK)

    def test_audit_that_codes(self):
        self.compare([CODE_AUDIT, CODE_REPLY, CONTRACT, CODE_REPLY], TASK)

    def test_task_with_a_signature_and_a_stated_format(self):
        stub = {
            **TASK,
            "prompt": 'def count_greater(arr, k):\n    """Count > k; return it as a string."""\n',
        }
        self.compare([ask(STRICT), CODE_REPLY, CONTRACT, CODE_REPLY], stub)

    def test_no_contract_falls_back_to_the_sampled_questions(self):
        replies = [ask(STRICT), "no code", ask(STRICT), ask(STRICT), CODE_REPLY]
        self.compare(replies, TASK)

    def test_a_refused_answer(self):
        replies = [ask(STRICT), CODE_REPLY, CONTRACT, CODE_REPLY]
        self.compare(replies, TASK, answer="Please ask one question at a time.")


class Z3OnCodeTest(unittest.TestCase):
    def test_the_audit_codes_and_z3_proves_a_conflict(self):
        proven = {"question": 'The task says "x", but the example "f(1) == 2" does not hold.'}
        original = laaser_contract.find_certificate
        laaser_contract.find_certificate = lambda *args, **kwargs: proven
        try:
            env = _FakeEnv([CODE_AUDIT, CODE_REPLY])
            LAASeR_Contract({**OFFLINE, "z3_mode": "on_code"}).run(env, TASK)
        finally:
            laaser_contract.find_certificate = original
        self.assertEqual(env.questions, [proven["question"]])
        self.assertFalse(any("Draft:" in p for p in env.prompts))

    def test_the_audit_codes_and_there_is_no_conflict(self):
        env = _FakeEnv([CODE_AUDIT])
        LAASeR_Contract({**OFFLINE, "z3_mode": "on_code"}).run(env, TASK)
        self.assertEqual(env.questions, [])

    def test_the_audit_asks_and_gets_the_contract_question(self):
        env = _FakeEnv([ask(STRICT), CODE_REPLY, CONTRACT, CODE_REPLY])
        LAASeR_Contract({**OFFLINE, "z3_mode": "on_code"}).run(env, TASK)
        self.assertTrue(env.questions[0].startswith("I will assume"))


class TimeBudgetTest(unittest.TestCase):
    def test_a_slow_llm_call_is_cut_and_the_task_still_returns(self):
        class SlowEnv(_FakeEnv):
            def llm(self, messages):
                time.sleep(5)
                return super().llm(messages)

        laaser_contract.LLM_CALL_TIMEOUT_S, original = 0.2, laaser_contract.LLM_CALL_TIMEOUT_S
        try:
            env = SlowEnv([ask(STRICT)] * 10)
            started = time.monotonic()
            code = LAASeR_Contract({**OFFLINE, "time_budget": 1}).run(env, TASK)
        finally:
            laaser_contract.LLM_CALL_TIMEOUT_S = original
        self.assertLess(time.monotonic() - started, 4)
        self.assertIsInstance(code, str)


class CallAdapterTest(unittest.TestCase):
    def test_a_call_that_binds_is_unchanged(self):
        namespace = {}
        exec(call_adapter("def f(a, b):\n    return (a, b)\n", "f"), namespace)
        self.assertEqual(namespace["f"](1, 2), (1, 2))


if __name__ == "__main__":
    unittest.main()
