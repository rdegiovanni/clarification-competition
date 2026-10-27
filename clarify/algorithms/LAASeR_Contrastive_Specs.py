# SPDX-FileCopyrightText: 2026 Submitter <submitter@email.com>
#
# SPDX-License-Identifier: Open Source License like MIT, Apache 2.0, ...

"""Algorithm name.

LAASeR with Repair loop algorithm.

We make the LLM aware that its output will be part of a competition.
We explain to it that the main goal is to implement the correct function,
but unnecessary questions are penalized.


Team: LAASeR - LIST
Team Members: Matias Brizzio, Jordi Cabot, Renzo Degiovanni
Main Contact: main.contact@email.com
"""

from __future__ import annotations

import ast
import json
from typing import Any

from clarify.baselines import ClarificationAlgorithmBase
from clarify.env import ClarificationEnvironment, LimitsExceededException, TooManyQuestionException
from clarify.runtime import _validate_and_parse_evalplus_result

# generation codes
FORMAT_ERROR = "IncorrectOutputFormat"
PARSING_ERROR = "SyntaxError"
PARSING_OK = "CorrectSyntax"
INVALID_ENTRYPOINT = "InvalidEntryPoint"

# answer codes
QUESTION_KEY = "QUESTION"

FORMALISE_PROMPT = """You write Nagini contracts (the nagini_contracts specification language, used by the Nagini
verifier for statically typed Python 3) for a Python function from its task description.

Nagini conventions:
- First line: `from nagini_contracts.contracts import *` (plus `from typing import List, Dict, Set, Optional, ...`).
- The function needs full type annotations. Use the signature from the description when it is given; otherwise
  derive types ONLY from what the description states.
- Preconditions: `Requires(<bool expr>)`. Postconditions: `Ensures(<bool expr>)`. Both are calls at the top of the
  function body, before any other statement.
- `Result()` is the return value. `Old(e)` is the value of e in the pre-state.
- Quantifiers: `Forall(range(len(xs)), lambda i: Implies(cond, body))`, `Exists(...)`, `Forall(int, lambda i: ...)`.
  Also `Implies(a, b)`.
- Mutable containers need permissions: `Acc(list_pred(xs))`, `Acc(dict_pred(d))`, `Acc(set_pred(s))` in both Requires
  and Ensures when the function reads them. Immutable values (int, bool, str, tuple) need none.
- Pure functions: `@Pure` decorator; use it when the function has no side effects and returns a value. For
  `@Pure` functions, do not use `Acc(...)` for the arguments you only read through `Requires`/`Ensures` when
  contract on the immutable type is enough.
- Exceptions: `Exsures(ValueError, <cond>)` only if the description says an exception is raised.
- The body must be just `...` (no implementation).

Rules:
- Encode ONLY what the description states or what its examples demonstrate. Do not invent constraints, defaults or
  tie-breaking rules. A weaker but true contract is better than a stronger guessed one.
- Every example in the description must satisfy the preconditions and the postconditions.
- Postconditions describe WHAT holds for the result, not HOW to compute it. No algorithms, no hidden-test guesses.
- If the contract cannot be inferred because one specific fact is missing, return "need_clarification" with a
  concrete reasoning. Otherwise return the contract and list open points under "assumptions".

Reply with one ```json block:
{"status": "ok" | "need_clarification",
 "contract": "...or null",
 "reasoning": "<max 80 words>",
 "assumptions": []}
 
TASK DESCRIPTION:
{prompt}

ENTRY_POINT:
{entry_point}
""".strip()

SPEC_INFERENCE = """You write Nagini contracts (the nagini_contracts specification language, used by the Nagini
verifier for statically typed Python 3) for a Python function from its implementation.

Nagini conventions:
- First line: `from nagini_contracts.contracts import *` (plus `from typing import List, Dict, Set, Optional, ...`).
- The function needs full type annotations. Use the signature from the description when it is given; otherwise
  derive types ONLY from what the description states.
- Preconditions: `Requires(<bool expr>)`. Postconditions: `Ensures(<bool expr>)`. Both are calls at the top of the
  function body, before any other statement.
- `Result()` is the return value. `Old(e)` is the value of e in the pre-state.
- Quantifiers: `Forall(range(len(xs)), lambda i: Implies(cond, body))`, `Exists(...)`, `Forall(int, lambda i: ...)`.
  Also `Implies(a, b)`.
- Mutable containers need permissions: `Acc(list_pred(xs))`, `Acc(dict_pred(d))`, `Acc(set_pred(s))` in both Requires
  and Ensures when the function reads them. Immutable values (int, bool, str, tuple) need none.
- Pure functions: `@Pure` decorator; use it when the function has no side effects and returns a value. For
  `@Pure` functions, do not use `Acc(...)` for the arguments you only read through `Requires`/`Ensures` when
  contract on the immutable type is enough.
- Exceptions: `Exsures(ValueError, <cond>)` only if the description says an exception is raised.

Rules:
- Encode ONLY what the code states. Do not invent constraints, defaults or
  tie-breaking rules. A weaker but true contract is better than a stronger guessed one.
- Postconditions describe WHAT holds for the result, not HOW to compute it. No algorithms, no hidden-test guesses.
- If the contract cannot be inferred because one specific fact is missing, return "need_clarification" with a
  concrete reasoning. Otherwise return the contract and list open points under "assumptions".

Reply with one ```json block:
{"status": "ok" | "need_clarification",
 "contract": "...or null",
 "reasoning": "<max 80 words>",
 "assumptions": []}

IMPLEMENTATION:
{prompt}

ENTRY_POINT:
{entry_point}
""".strip()

SPEC_EQUIVALENCE = """You analyse two Nagini contracts (the nagini_contracts specification language, used by the Nagini
verifier for statically typed Python 3) for the same Python function.

Rules:
- Compare the two pre-conditions and check if these are equivalent. If not, provide at least one counter-example, 
  i.e., an input that satisfies one pre-condition but not the other.
- Compare the two post-conditions and check if these are equivalent. If not, provide at least one counter-example (an input)
  in which the post-conditions evaluate to different values. 
- If the pre-conditions and post-conditions are equivalent answer "equivalent"; otherwise answer "need_clarification" 
  with the concrete reasoning and counterexamples. 

Reply with one ```json block:
{"verdict": "equivalent" | "need_clarification",
 "reasoning": "<max 80 words>",
}

SPECIFICATION 1:
{spec_1}

SPECIFICATION 2
{spec_2}
""".strip()


QUESTION_PROMPT = """You help clarify a buggy programming-task description by asking the user ONE question.

TASK DESCRIPTION:
{prompt}

JUDGE FINDINGS (may be noisy):
{findings}

PREVIOUSLY ASKED: (do not repeat):
{history}


Write ONE clarifying question that satisfies ALL of:
- Critical: it resolves a real blocker to a correct implementation.
- Not guessable: the answer cannot be reliably inferred by convention.
- Objective: it admits a single unambiguous answer. Where possible, give concrete
  alternatives or a concrete input with the output you would expect.

If the description is already sufficient, return {{"question": null}}.
Answer ONLY with JSON: {{"question": "<text or null>"}}"""

EVOLVE_PROMPT = """You maintain a programming-task description. A Judge identified an issue for which
we ask a clarification question to a user. 

TASK DESCRIPTION:
{prompt}

JUDGE FINDINGS (may be noisy):
{findings}

CLARIFICATION QUESTION:
{question}

CLARIFICATION ANSWER:
{question}

Rewrite the description so that it states the fact the answer establishes, as if the original author had
written it.

Rules:
- Keep everything the answer does not contradict: wording, examples, the function name. Keep the same format (if the
  description is a docstring, return a docstring).
- Add only what the answer states. No default readings, no examples you computed, no implementation hints, no
  guesses about what the answer leaves open.
- If the answer replaces an earlier statement, replace it; never keep two conflicting statements.
- If the answer states the arguments, write "The function takes ..." with their number and kinds.
- If the answer is partial, evasive or states no fact, set changed to false and return the description unchanged.

Reply with one ```json block:
{"changed": true, "description": "the full rewritten description"}"""

FIX_PROMPT = """You maintain a programming-task description for which a Judge identified an issue. 

TASK DESCRIPTION:
{prompt}

JUDGE FINDINGS (may be noisy):
{findings}

Rewrite the description so that it fixes the identified Judge issues, as if the original author had
written it.

Rules:
- Keep everything the findings does not contradict.
- Add only things to fix what the findings states. 

Reply with one ```json block:
{"changed": true, "description": "the full rewritten description"}"""

IMPL_PROMPT = """Implement the Python function `{entry}` for the task below.
Use only the standard library. Return ONLY one ```python code block containing the
complete implementation (imports and the function). Do not ask questions.

{prompt}
"""

IMPL_CONTRACT_PROMPT = """Implement the Python function `{entry}` for the pre and post conditions below.
Use only the standard library. Return ONLY one ```python code block containing the
complete implementation (imports and the function). Do not ask questions.

{contract}
"""

REPAIR_FORMAT_ERROR_TEMPLATE = """
For the given coding task, you generated a response that does not follow the expected output format. 
Please fix it.

Response:
{response}

Error Message:
{msg}

The expected format must enclose the response in ```python and ```
""".strip()

REPAIR_INVALID_ENDPOINT_TEMPLATE = """
You generated a response using an invalid function name (entry_point). 
Please fix it.

Response:
{response}

entry_point:
The function must be named exactly `{entry_point}`.
""".strip()

REPAIR_PARSING_ERROR_TEMPLATE = """
You generated a response that is not python syntax correct and thus the parsing failed. 
Please fix it.

Task Description:
{prompt}

Response:
{response}

entry_point:
The function must be named exactly `{entry_point}`.

Error Message:
{msg}

Output Format:
The response must be enclosed in ```python and ```
""".strip()


def _generate_question(env: ClarificationEnvironment, gen_prompt: str, response: dict[str, Any],
                       history: list[str]) -> dict[str, Any]:
    findings = f"[{response.get("issue_type")}] {response.get('reasoning', '')}\n"

    messages = [
        {
            "role": "user",
            "content": (
                QUESTION_PROMPT.replace("{prompt}", gen_prompt).replace(
                    "{findings}", findings).replace("{history}", str(history))
            ),
        }
    ]

    return _parse_json(env.llm(messages))


def _evolve_prompt(env: ClarificationEnvironment, gen_prompt: str, response: dict[str, Any], question: str,
                   answer: str) -> dict[str, Any]:
    findings = f"[{response.get("issue_type")}] {response.get('reasoning', '')}"

    messages = [
        {
            "role": "user",
            "content": (
                EVOLVE_PROMPT.replace("{prompt}", gen_prompt).replace(
                    "{findings}", findings).replace("{question}", question).replace(
                    "{answer}", answer
                )
            ),
        }
    ]

    return _parse_json(env.llm(messages))


def _fix_prompt(env: ClarificationEnvironment, gen_prompt: str, response: dict[str, Any]) -> dict[str, Any]:
    findings = f"[{response.get("issue_type")}] {response.get('reasoning', '')}"

    messages = [
        {
            "role": "user",
            "content": (
                FIX_PROMPT.replace("{prompt}", gen_prompt).replace(
                    "{findings}", findings)
            ),
        }
    ]

    return _parse_json(env.llm(messages))


def _formalise_prompt(env: ClarificationEnvironment, prompt, entry_point, prompt_formalisation: bool) -> dict[str, Any]:
    if prompt_formalisation:
        formalisation_prompt = FORMALISE_PROMPT.replace("{prompt}", prompt).replace(
                    "{entry_point}", entry_point)
    else:
        formalisation_prompt = SPEC_INFERENCE.replace("{prompt}", prompt).replace(
            "{entry_point}", entry_point)
    messages = [
        {
            "role": "user",
            "content": formalisation_prompt,
        }
    ]
    response = env.llm(messages)
    return _parse_json(response)


def _check_equivalence(env: ClarificationEnvironment, spec_prompt, spec_code) -> dict[str, Any]:
    messages = [
        {
            "role": "user",
            "content": SPEC_EQUIVALENCE.replace("{spec_1}", spec_prompt).replace(
            "{spec_2}", spec_code)
        }
    ]
    response = env.llm(messages)
    return _parse_json(response)


def _code_generation(env: ClarificationEnvironment, gen_prompt: str, entry_point: str) -> str:
    messages = [
        {
            "role": "user",
            "content": (
                IMPL_PROMPT.replace("{prompt}", gen_prompt).replace(
                    "{entry_point}", entry_point)
            ),
        }
    ]

    return env.llm(messages)


def _repair_format_error(env: ClarificationEnvironment, response: str, msg: str) -> str:
    messages = [
        {
            "role": "user",
            "content": (REPAIR_FORMAT_ERROR_TEMPLATE.format(response=response, msg=msg)),
        }
    ]

    return env.llm(messages)


def _repair_invalid_entrypoint(
        env: ClarificationEnvironment, entry_point: str, response: str
) -> str:
    messages = [
        {
            "role": "user",
            "content": (
                REPAIR_INVALID_ENDPOINT_TEMPLATE.format(entry_point=entry_point, response=response)
            ),
        }
    ]

    return env.llm(messages)


def _repair_parsing_error(
        env: ClarificationEnvironment, gen_prompt: str, entry_point: str, response: str, msg: str
) -> str:
    messages = [
        {
            "role": "user",
            "content": (
                REPAIR_PARSING_ERROR_TEMPLATE.format(prompt=gen_prompt, entry_point=entry_point,
                                                     response=response, msg=msg)
            ),
        }
    ]

    return env.llm(messages)


def _is_solution_plausible(response: str, entry_point: str) -> (str, str):
    try:
        code = _validate_and_parse_evalplus_result(response)
    except ValueError as e:
        return FORMAT_ERROR, str(e)

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return PARSING_ERROR, str(e)

    if any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entry_point
            for node in ast.walk(tree)
    ):
        return PARSING_OK, code
    else:
        return INVALID_ENTRYPOINT, code


def _parse_json(text: Any) -> dict[str, Any]:
    """Extract a JSON object from a ```json block or from bare text. Always returns a dict."""
    # text = _as_text(text)
    try:
        data = json.loads(text)
        return data
    except Exception:
        return {}


def _implement(env: ClarificationEnvironment, prompt: str, entry_point: str) -> str:

    code = _code_generation(env, prompt, entry_point)
    max_retry = 0
    while True:
        status, msg = _is_solution_plausible(code, entry_point)
        if status == PARSING_OK or max_retry >= 5:
            return code
        elif status == FORMAT_ERROR:
            code = _repair_format_error(env, code, msg)
        elif status == INVALID_ENTRYPOINT:
            code = _repair_invalid_entrypoint(env, entry_point, code)
        else:  # status == PARSING_ERROR:
            code = _repair_parsing_error(env, prompt, entry_point, code, msg)
        max_retry += 1


def _implement_from_contract(env: ClarificationEnvironment, entry_point: str, formalisation: str) -> str:
    messages = [
        {
            "role": "user",
            "content": (
                IMPL_CONTRACT_PROMPT.replace("{contract}", formalisation).replace(
                    "{entry_point}", entry_point)
            ),
        }
    ]

    return env.llm(messages)


JUDGE_PROMPT = """You are judging whether a programming-task description is CORRECT.

Decide whether it is accurate, consistent, and internally coherent.

Rules:
1. Consistency: If any example's output contradicts the stated logic, the description is INCORRECT.
2. Completeness: Is a constraint, filter, condition, edge-case rule or output type missing
   that would change which inputs qualify or how output is computed?
3. Clarity/Ambiguity: Would competent programmers following standard conventions
   (0-indexing, usual tie-breaking, natural reading of the task name) converge on the
   same behavior?
4. Signature clarity: Is the function signature determinable? Check three things:
   (a) the NUMBER of input arguments,
   (b) the TYPE of each input argument (int, float, str, list of X, tuple, ...),
   (c) the TYPE or form of the output (bool, single value, list, count, string, ...).
   The signature is clear if a `def` gives it, if an example call shows it, or if the
   sentence states it unambiguously (for example "a list of integers" is one list argument).
   It is NOT clear if programmers could reasonably choose a different number of arguments,
   a different argument type, or a different return form.
5. If you can precisely guess and solve the issues in points 1..4, then judge the description as FIXABLE. 
   Otherwise, if user clarification is mandatory, judge the description as INCORRECT.
6. If none the previous points apply, and you have all the details to implement the python function, 
   judge the description as CORRECT.

Answer ONLY with a JSON object, no other text:
{"verdict": "correct" | "incorrect | fixable", "reasoning": "<max 80 words>", 
"issue_type": "none" | "ambiguity" | "incompleteness" | "contradiction"  | "signature"}
Use issue_type "none" if and only if verdict is "correct".

TASK DESCRIPTION:
{prompt}

ENTRY_POINT:
{entry_point}
""".strip()
def _analyse_prompt(env: ClarificationEnvironment, gen_prompt, entry_point) -> dict[str, Any]:
    messages = [
        {
            "role": "user",
            "content": (
                JUDGE_PROMPT.replace("{prompt}", gen_prompt).replace(
                    "{entry_point}", entry_point)
            ),
        }
    ]
    response = env.llm(messages)
    return _parse_json(response)



class LAASeR_Evolution(ClarificationAlgorithmBase):
    def run(self, env: ClarificationEnvironment, problem: dict[str, Any]) -> str:
        entry_point = problem["entry_point"]
        prompt = problem["prompt"]
        code = ""
        spec_prompt = ""
        spec_code = ""
        questions = []
        answers = []
        try:
            # Phase 1: Analyse and Evolve prompt with/without human clarification, until is ready to code
            while True:
                # check prompt status
                response = _analyse_prompt(env, prompt, entry_point)

                if response.get("verdict") == "correct":  # ready to code
                    break

                if response.get("verdict") == "fixable":
                    evolved_prompt = _fix_prompt(env, prompt, response)
                    if evolved_prompt.get("changed"):
                        prompt = evolved_prompt.get("description")
                        continue

                # response.get("verdict") == "incorrect" or fix did not succeed.
                # Ask the user for clarification
                if not env.can_ask():
                    break
                clarifying_question = _generate_question(env, prompt, response, questions).get("question")
                if clarifying_question is not None and clarifying_question != "null":
                    questions.append(clarifying_question)
                else:
                    break
                clarification_answer = env.ask_human(clarifying_question)
                answers.append(clarification_answer)
                evolved_prompt = _evolve_prompt(env, prompt, response, clarifying_question, clarification_answer)
                if evolved_prompt.get("changed"):
                    prompt = evolved_prompt.get("description")
                else:
                    break

            # Phase 2: Contrastive analysis
            while True:
                spec_prompt = _formalise_prompt(env, prompt, entry_point, True)
                code = _implement(env, prompt, entry_point)
                spec_code = _formalise_prompt(env, code, entry_point, False)

                evolved_prompt = ""
                if spec_prompt.get("status") == "ok" and spec_code.get("status") == "ok":
                    equiv_check = _check_equivalence(env, spec_prompt.get("contract"), spec_code.get("contract"))
                    if equiv_check.get("verdict") == "equivalent":
                        break
                    else:
                        equiv_check["issue_type"] = "not equivalent specifications"
                        evolved_prompt = _fix_prompt(env, prompt, equiv_check)
                elif spec_prompt.get("status") != "ok":
                    spec_prompt["issue_type"] = "formalisation failure"
                    evolved_prompt = _fix_prompt(env, prompt, spec_prompt)
                elif spec_code.get("status") != "ok":
                    spec_code["issue_type"] = "formalisation failure"
                    evolved_prompt = _fix_prompt(env, prompt, spec_code)

                if evolved_prompt.get("changed"):
                    prompt = evolved_prompt.get("description")
                else:
                    break

        except TooManyQuestionException as e:
            print("---> LAASeR: TooManyQuestionException")
            print(e)
        except LimitsExceededException as e:
            print("---> LAASeR: LimitsExceededException")
            print(e)
        except Exception as e:
            # The response might not contain an answer, assume a question is raised.
            print("---> LAASeR: Exception")
            print(e)
        finally:
            return code
