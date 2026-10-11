# SPDX-FileCopyrightText: 2026 Submitter <submitter@email.com>
#
# SPDX-License-Identifier: Open Source License like MIT, Apache 2.0, ...

"""Algorithm name.

LAASeR with universal self-stated-example verification, on top of multi-hypothesis discovery.

Fase 3 challenger #11. "Code ran but produced the wrong output" is the single largest failure
category across every challenger measured so far (`scripts/analyze_failures.py`'s taxonomy,
55/104 failures). An earlier draft of this idea parsed literal doctests (">>> ...") out of the
task prompt and verified the candidate against those -- correctly flagged by the team as too
narrow: most MBPP prompts contain no worked examples at all, so that version would do nothing for
the majority of the dataset.

This version generalizes it: instead of depending on the prompt happening to contain examples,
the DRAFT step is asked to state 2-3 concrete (arguments, expected output) pairs that IT believes
its OWN implementation must satisfy -- for every task, regardless of whether the prompt gives any
examples itself. The candidate is then actually run against those self-stated examples via
env.exec_code. A mismatch is unambiguous, execution-confirmed evidence of an implementation bug
(the model's own stated intent disagrees with what its code actually does) rather than a
clarification problem, so it is fixed with one targeted repair call instead of a question -- this
never touches the clarification budget. Honest scope: this does not catch cases where the model is
consistently wrong (its stated example and its code share the same misunderstanding of the task,
as documented for `HumanEval/55` in `docs/failure-analysis.md`) -- it targets implementation slips
where intent and code disagree with each other, which execution can detect without needing to know
the real answer.

Whatever candidate results (fixed or not) proceeds unchanged into `LAASeR_GateV3`'s
execution-verified multi-hypothesis ALT_PROBE step. Reuses the champion's format/entry-point/
parsing-error repair handlers unchanged.

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
MAX_SELFCHECK_REPAIRS = 2
_BLOCK_SEP_RE = re.compile(r"\n-{3,}\n")
_SELFCHECK_FALSE_RE = re.compile(r"SELFCHECK_(\d+)=False actual=(.*?) expected=")

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

Then write an "EXAMPLES:" section: a plain Python literal list of 2-3 (arguments, expected_output)
pairs that YOU believe your implementation below must satisfy, e.g.
EXAMPLES: [((3.5,), 0.5), ((-2, 4), 2)] -- the first element of each pair is a tuple of the
arguments you would pass to `{entry_point}`, the second is the exact value you expect it to
return for them. If the task text already states examples, restate them here; otherwise state
what you believe should happen. If you truly cannot think of any concrete example, write
"EXAMPLES: none".

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

SELFCHECK_REPAIR_TEMPLATE = """
You stated that your implementation of `{entry_point}` should satisfy this example:
Call: `{entry_point}{args}`
Expected output: `{expected}`

But when your candidate below is actually run on that input, it returns: `{actual}`

```python
{code}
```

Please fix the implementation so it correctly satisfies this example (while still solving the
task). Write READY_TO_CODE followed by ```python and ``` with the corrected implementation.
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

SELFCHECK_SCRIPT_TEMPLATE = """
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


fn, err = _load("{code_b64}", "{entry_point}")

examples = {examples_repr}

for i, (args, expected) in enumerate(examples):
    if err:
        actual = err
    else:
        try:
            actual = fn(*args)
        except Exception as e:
            actual = "ERROR:" + type(e).__name__
    print(
        "SELFCHECK_" + str(i) + "=" + str(actual == expected)
        + " actual=" + repr(actual) + " expected=" + repr(expected)
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


def _self_check_repair(
    env: ClarificationEnvironment,
    entry_point: str,
    args: tuple,
    expected: Any,
    actual_text: str,
    code: str,
) -> str:
    messages = [
        {
            "role": "user",
            "content": (
                SELFCHECK_REPAIR_TEMPLATE.replace("{entry_point}", entry_point)
                .replace("{args}", repr(args))
                .replace("{expected}", repr(expected))
                .replace("{actual}", actual_text)
                .replace("{code}", code)
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

    preamble = response.split("```python", 1)[0].replace(READY_TO_CODE_KEY, "").strip()
    assumptions = preamble
    examples: list[tuple[tuple, Any]] = []
    if "EXAMPLES:" in preamble:
        assumptions, _, examples_text = preamble.partition("EXAMPLES:")
        assumptions = assumptions.strip()
        try:
            parsed = ast.literal_eval(examples_text.strip())
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], tuple):
                        examples.append(item)
        except (ValueError, SyntaxError):
            pass

    return PARSING_OK, (code, assumptions, examples)


def _build_selfcheck_script(entry_point: str, code: str, examples: list[tuple[tuple, Any]]) -> str:
    code_b64 = base64.b64encode(code.encode()).decode()
    return (
        SELFCHECK_SCRIPT_TEMPLATE.replace("{code_b64}", code_b64)
        .replace("{entry_point}", entry_point)
        .replace("{examples_repr}", repr(examples))
    )


def _self_check_and_repair(
    env: ClarificationEnvironment,
    entry_point: str,
    code: str,
    examples: list[tuple[tuple, Any]],
) -> str:
    if not examples:
        return code

    for attempt in range(MAX_SELFCHECK_REPAIRS + 1):
        probe_script = _build_selfcheck_script(entry_point, code, examples)
        probe_output = env.exec_code(probe_script)
        match = _SELFCHECK_FALSE_RE.search(probe_output)
        if match is None:
            return code
        if attempt == MAX_SELFCHECK_REPAIRS:
            return code  # give up: exhausted repair attempts, submit last candidate as-is

        idx = int(match.group(1))
        actual_text = match.group(2)
        args, expected = examples[idx]
        repair_response = _self_check_repair(env, entry_point, args, expected, actual_text, code)
        new_status, payload = _parse_draft(repair_response, entry_point)
        if new_status == PARSING_OK:
            code = payload[0]
        else:
            return code  # malformed repair: give up with the last good candidate

    return code


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


class LAASeR_GateV7(ClarificationAlgorithmBase):
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
                        code, assumptions, examples = payload
                        candidate = code  # commit the valid draft before the riskier self-check
                        candidate = _self_check_and_repair(env, entry_point, candidate, examples)
                        status = ALT_PROBE
                    else:
                        status = new_status
                else:
                    status = FORMAT_ERROR

        except TooManyQuestionException:
            print("---> LAASeR_GateV7: TooManyQuestionException")
        except LimitsExceededException:
            print("---> LAASeR_GateV7: LimitsExceededException")
        except Exception:
            print("---> LAASeR_GateV7: Exception")
        finally:
            return candidate  # noqa: B012 -- intentional: always return best-so-far candidate
