# SPDX-FileCopyrightText: 2026 Submitter <submitter@email.com>
#
# SPDX-License-Identifier: Open Source License like MIT, Apache 2.0, ...

"""Algorithm name.

LAASeR with multi-hypothesis discovery, verified by execution.

Fase 3 challenger #7. `LAASeR_GateV2` (challenger #6) proved an execution-grounded divergence
check beats a self-judged gate (clarification rate 100% -> 43.33%, nDCG stayed far above the
champion's) -- but it tests only the SINGLE assumption its DRAFT step happens to self-select,
which bottlenecks recall: a `scripts/analyze_failures.py` taxonomy run showed it asks about the
signature/arity bug class only 2/6 times vs. v1's 6/6, because the one assumption it picks is
usually something else.

This version is closer to the full method of the "behavior-changing questions" paper this family
is based on (arXiv:2610.01769): rather than verify a single self-picked hypothesis, the ALT+PROBE
call may return UP TO 3 candidate hypotheses (one per uncertain assumption, in most-to-least
uncertain order), all qualified in a single combined env.exec_code probe script, and the question
asked belongs to the FIRST candidate (in that order) that shows a confirmed behavioral divergence.
This is still one extra LLM call and one extra exec_code call per round, regardless of how many
hypotheses are tested -- same cost shape as v2, more recall. Reuses the champion's
format/entry-point/parsing-error repair handlers unchanged -- not part of this hypothesis.

Team: LAASeR - LIST
Team Members: Matias Brizzio, Jordi Cabot, Renzo Degiovanni
Main Contact: main.contact@email.com
"""

from __future__ import annotations

import ast
import base64
import re
from typing import Any

from clarify.baselines import ClarificationAlgorithmBase
from clarify.env import ClarificationEnvironment, LimitsExceededException, TooManyQuestionException
from clarify.runtime import _validate_and_parse_evalplus_result

# generation codes
CODE_GEN = "CODE_GEN"
FORMAT_ERROR = "IncorrectOutputFormat"
PARSING_ERROR = "SyntaxError"
PARSING_OK = "CorrectSyntax"
INVALID_ENTRYPOINT = "InvalidEntryPoint"
ALT_PROBE = "ALT_PROBE"

# answer codes
READY_TO_CODE_KEY = "READY_TO_CODE"

MAX_DRAFT_ATTEMPTS = 8
MAX_CANDIDATES = 3
_BLOCK_SEP_RE = re.compile(r"\n-{3,}\n")

DRAFT_TEMPLATE = """
Please find below a coding task.
Task:
`{prompt}`

Important: the function must be named exactly `{entry_point}` independently of the task text above.

First, write a short "ASSUMPTIONS:" section (plain bullet points) listing anything you had to
infer that is NOT explicitly stated in the task text above -- in particular: whether there might
be a parameter the task text never names (a common convention for array/list functions is a
redundant length argument alongside the array itself), any edge case, sign, range, or type you
assumed, and any default or tie-break behavior you chose. If there is truly nothing you had to
infer, write "ASSUMPTIONS: none".

Then write READY_TO_CODE followed by ```python and ``` containing your best implementation.

Notice that you will be participating in a prompt clarification competition, where the goal is to
implement the correct python function, but unnecessary clarification turns are penalized -- so
write your best candidate directly here. You will get a separate chance to ask a question only if
one of your own listed assumptions turns out to be genuinely critical.
""".strip()

ALT_PROBE_TEMPLATE = """
You drafted the candidate implementation below for a coding task, along with a list of
assumptions you made because the task text did not state them explicitly.

Candidate:
```python
{candidate}
```

Your stated assumptions:
`{assumptions}`

Consider the assumptions above that you are genuinely unsure about. If there is more than one,
take at most the 3 you are LEAST sure about, ordered from most to least uncertain. If none of
your assumptions would change whether the candidate is correct, or you listed no assumptions,
write exactly DONE and nothing else.

Otherwise, for EACH of those (up to 3) uncertain assumptions, write a block in this exact format:

ASSUMPTION: <restate the one assumption>
ALTERNATIVE:
```python
<a full alternative implementation of the SAME function that makes the OPPOSITE or a materially
different choice for that one assumption, keeping everything else the same>
```
INPUTS: <a plain Python literal list of argument tuples that would be passed to `{entry_point}`
exactly as you defined it in your candidate above, e.g. [(1, 2), (3, -1)] -- choose inputs you
believe would make your candidate and this alternative disagree>
QUESTION: <exactly ONE atomic, concrete, closed-form question that confirms or denies a SINGLE
specific fact about a SINGLE specific input -- not an abstract or open-ended question, not more
than one sub-question, and never asking the user to write code or reveal test cases>

Separate consecutive blocks with a line that contains exactly: ---
""".strip()

REPAIR_FORMAT_ERROR_TEMPLATE = """
For the given coding task, you generated a response that does not follow the expected output format.
Please fix it.

Response:
`{response}`

The expected format must enclose the response in ```python and ```
""".strip()

REPAIR_INVALID_ENDPOINT_TEMPLATE = """
You generated a response using an invalid function name (entry_point).
Please fix it.

Response:
`{response}`

entry_point:
The function must be named exactly `{entry_point}`.
""".strip()

REPAIR_PARSING_ERROR_TEMPLATE = """
You generated a response that is not python syntax correct and thus the parsing failed.
Please fix it.

Task:
`{prompt}`

Response:
`{response}`

entry_point:
The function must be named exactly `{entry_point}`.

Output Format:
The response must be enclosed in ```python and ```
""".strip()

PROBE_SCRIPT_TEMPLATE = """
import base64


def _load(src_b64, name):
    try:
        src = base64.b64decode(src_b64).decode()
    except Exception as e:
        return None, "DECODE_ERROR:" + type(e).__name__
    ns = {}
    try:
        exec(src, ns)
    except Exception as e:
        return None, "LOAD_ERROR:" + type(e).__name__
    fn = ns.get(name)
    if fn is None:
        return None, "LOAD_ERROR:missing_function"
    return fn, None


fn_orig, err_orig = _load("{orig_b64}", "{entry_point}")

candidates = {candidates_literal}

for ci, (alt_b64, inputs) in enumerate(candidates):
    fn_alt, err_alt = _load(alt_b64, "{entry_point}")
    for ii, args in enumerate(inputs):
        if err_orig:
            ra = err_orig
        else:
            try:
                ra = fn_orig(*args)
            except Exception as e:
                ra = "ERROR:" + type(e).__name__
        if err_alt:
            rb = err_alt
        else:
            try:
                rb = fn_alt(*args)
            except Exception as e:
                rb = "ERROR:" + type(e).__name__
        print(
            "DIVERGE_" + str(ci) + "_" + str(ii) + "=" + str(ra != rb)
            + " A=" + repr(ra) + " B=" + repr(rb)
        )
""".strip()


def _draft(
    env: ClarificationEnvironment, problem: dict[str, Any], clarifications: list[str]
) -> str:
    gen_prompt = problem["prompt"]
    entry_point = problem["entry_point"]
    if len(clarifications) > 0:
        gen_prompt += "\n\nClarifications:\n"
        for c in clarifications:
            gen_prompt += c

    messages = [
        {
            "role": "user",
            "content": (
                DRAFT_TEMPLATE.replace("{prompt}", gen_prompt).replace("{entry_point}", entry_point)
            ),
        }
    ]

    return env.llm(messages)


def _alt_probe(
    env: ClarificationEnvironment, candidate: str, assumptions: str, entry_point: str
) -> str:
    messages = [
        {
            "role": "user",
            "content": (
                ALT_PROBE_TEMPLATE.replace("{candidate}", candidate)
                .replace("{assumptions}", assumptions or "none")
                .replace("{entry_point}", entry_point)
            ),
        }
    ]

    return env.llm(messages)


def _repair_format_error(env: ClarificationEnvironment, response: str) -> str:
    messages = [
        {
            "role": "user",
            "content": (REPAIR_FORMAT_ERROR_TEMPLATE.replace("{response}", response)),
        }
    ]

    return READY_TO_CODE_KEY + "\n" + env.llm(messages)


def _repair_invalid_entrypoint(
    env: ClarificationEnvironment, problem: dict[str, Any], response: str
) -> str:
    entry_point = problem["entry_point"]
    messages = [
        {
            "role": "user",
            "content": (
                REPAIR_INVALID_ENDPOINT_TEMPLATE.replace("{entry_point}", entry_point).replace(
                    "{response}", response
                )
            ),
        }
    ]

    return READY_TO_CODE_KEY + "\n" + env.llm(messages)


def _repair_parsing_error(
    env: ClarificationEnvironment, problem: dict[str, Any], clarifications: list[str], response: str
) -> str:
    gen_prompt = problem["prompt"]
    entry_point = problem["entry_point"]
    if len(clarifications) > 0:
        gen_prompt += "\n\nClarifications:\n"
        for c in clarifications:
            gen_prompt += c

    messages = [
        {
            "role": "user",
            "content": (
                REPAIR_PARSING_ERROR_TEMPLATE.replace("{prompt}", gen_prompt)
                .replace("{entry_point}", entry_point)
                .replace("{response}", response)
            ),
        }
    ]

    return READY_TO_CODE_KEY + "\n" + env.llm(messages)


def _parse_draft(response: str, entry_point: str) -> tuple[str, Any]:
    try:
        code = _validate_and_parse_evalplus_result(response)
    except ValueError as e:
        return FORMAT_ERROR, str(e)

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return PARSING_ERROR, str(e)

    if not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entry_point
        for node in ast.walk(tree)
    ):
        return INVALID_ENTRYPOINT, code

    assumptions = response.split("```python", 1)[0].replace(READY_TO_CODE_KEY, "").strip()
    return PARSING_OK, (code, assumptions)


def _parse_block(block: str) -> tuple[str, list, str] | None:
    if "ALTERNATIVE:" not in block or "INPUTS:" not in block or "QUESTION:" not in block:
        return None

    try:
        alt_code = _validate_and_parse_evalplus_result(block)
    except ValueError:
        return None

    try:
        _, after_inputs = block.split("INPUTS:", 1)
        inputs_text, _, question_text = after_inputs.partition("QUESTION:")
        inputs = ast.literal_eval(inputs_text.strip())
    except (ValueError, SyntaxError):
        return None

    if not isinstance(inputs, list) or len(inputs) == 0:
        return None
    if not all(isinstance(args, tuple) for args in inputs):
        return None

    question = question_text.strip()
    if not question:
        return None

    return alt_code, inputs, question


def _parse_candidates(response: str) -> list[tuple[str, list, str]]:
    if "ALTERNATIVE:" not in response:
        return []

    candidates = []
    for block in _BLOCK_SEP_RE.split(response):
        parsed = _parse_block(block)
        if parsed is not None:
            candidates.append(parsed)
    return candidates[:MAX_CANDIDATES]


def _build_combined_probe_script(
    entry_point: str, original_code: str, candidates: list[tuple[str, list]]
) -> str:
    orig_b64 = base64.b64encode(original_code.encode()).decode()
    lines = []
    for alt_code, inputs in candidates:
        alt_b64 = base64.b64encode(alt_code.encode()).decode()
        lines.append(f"    ({alt_b64!r}, {inputs!r}),")
    candidates_literal = "[\n" + "\n".join(lines) + "\n]"

    return (
        PROBE_SCRIPT_TEMPLATE.replace("{orig_b64}", orig_b64)
        .replace("{entry_point}", entry_point)
        .replace("{candidates_literal}", candidates_literal)
    )


class LAASeR_GateV3(ClarificationAlgorithmBase):
    def run(self, env: ClarificationEnvironment, problem: dict[str, Any]) -> str:
        clarifications: list[str] = []
        candidate = ""
        assumptions = ""
        try:
            entry_point = problem["entry_point"]
            status = CODE_GEN
            response = ""
            draft_attempts = 0
            while True:
                if status == ALT_PROBE:
                    alt_response = _alt_probe(env, candidate, assumptions, entry_point)
                    hypotheses = _parse_candidates(alt_response)
                    if not hypotheses:
                        return candidate  # DONE, or malformed: fail safe, never ask

                    probe_script = _build_combined_probe_script(
                        entry_point, candidate, [(h[0], h[1]) for h in hypotheses]
                    )
                    probe_output = env.exec_code(probe_script)

                    selected = None
                    for ci in range(len(hypotheses)):
                        if re.search(rf"DIVERGE_{ci}_\d+=True", probe_output):
                            selected = hypotheses[ci]
                            break

                    if selected is None:
                        return candidate  # no confirmed divergence anywhere: never ask

                    _, _, question = selected
                    clarification = env.ask_human(question)
                    num_rounds = len(clarifications)
                    clarifications += [
                        f"Question #{num_rounds + 1}:\n{question}\nAnswer:\n{clarification}\n"
                    ]
                    status = CODE_GEN
                    continue

                if draft_attempts >= MAX_DRAFT_ATTEMPTS:
                    return candidate
                draft_attempts += 1

                if status == CODE_GEN:
                    response = _draft(env, problem, clarifications)
                elif status == FORMAT_ERROR:
                    response = _repair_format_error(env, response)
                elif status == INVALID_ENTRYPOINT:
                    response = _repair_invalid_entrypoint(env, problem, response)
                else:  # PARSING_ERROR
                    response = _repair_parsing_error(env, problem, clarifications, response)

                if READY_TO_CODE_KEY in response:
                    new_status, payload = _parse_draft(response, entry_point)
                    if new_status == PARSING_OK:
                        candidate, assumptions = payload
                        status = ALT_PROBE
                    else:
                        status = new_status
                else:
                    status = FORMAT_ERROR

        except TooManyQuestionException:
            print("---> LAASeR_GateV3: TooManyQuestionException")
        except LimitsExceededException:
            print("---> LAASeR_GateV3: LimitsExceededException")
        except Exception:
            print("---> LAASeR_GateV3: Exception")
        finally:
            return candidate  # noqa: B012 -- intentional: always return best-so-far candidate
