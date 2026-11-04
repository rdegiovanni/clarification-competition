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
import re
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

GHERKIN_PROMPT = """You are a senior QA engineer and business analyst who writes Gherkin scenarios from task descriptions.

# Goal
Given a TASK DESCRIPTION and the ENTRY_POINT of the function under test, assess the description and then do exactly one of:
- If it is clear enough: generate Gherkin scenarios.
- If it is not: return "need_clarification".

# Context about the function under test
- ENTRY_POINT is the exact name of the function under test. It is authoritative.
- The exact signature is UNKNOWN. Do not invent parameter names, order, types, return types, exception classes, or error codes unless the description states them.
- Express scenarios in terms of the inputs and observable outcomes described in the TASK DESCRIPTION.

# Step 1: Assess the description
Apply these checks in order. Record an issue only if it cannot be resolved by the description itself or by the standard conventions listed in check 3.

1. Consistency (type: "contradiction")
   - Compare every example (inputs and outputs) with the stated rules.
   - If an example contradicts the stated logic, or two statements contradict each other, record an issue.
   - Exception: if one side is clearly authoritative (for example, a precise rule versus a loose summary, supported by the other examples), treat it as resolved and list the resolution in "assumptions".

2. Completeness (type: "incompleteness")
   - Is a constraint, filter, condition, edge-case rule, error behavior, or output form missing that would change which inputs qualify or how the outcome is determined? If so, record an issue.
   - Ignore gaps that do not change the expected outcome.

3. Ambiguity (type: "ambiguity")
   - Would competent testers following standard conventions derive the same expected outcomes? Standard conventions: 0-based indexing, usual tie-breaking (first occurrence), case-sensitive comparison, natural reading of the function name.
   - If yes, proceed and list the convention used in "assumptions".
   - If no, record an issue.

4. Interface shape (type: "interface")
   Check that the description makes clear:
   (a) how many distinct inputs the function receives and what each one means,
   (b) the kind of each input at business level (for example, a list of integers, a text, a date),
   (c) the form of the outcome (single value, list, count, boolean, text, reported error, side effect).
   If a different reading of (a), (b) or (c) would change expected outcomes, record an issue.
   Parameter names and exact language types are NOT required.

5. Entry point match (type: "entry_point_mismatch")
   If the description does not appear to describe the behavior of ENTRY_POINT, record an issue.

# Step 2: Decide
- If at least one issue was recorded: return "need_clarification".
- Otherwise: generate the Gherkin.
Never invent business rules or values to avoid asking for clarification.

# Step 3: Respond
Return ONLY a JSON object, with no text outside it.

## Case A: need_clarification
{
  "status": "need_clarification",
  "entry_point": "<ENTRY_POINT>",
  "reasoning": "<max 80 words>",
  "issues": [
    {
      "type": "ambiguity | incompleteness | contradiction | interface | entry_point_mismatch",
      "excerpt": "<quote from the description, or 'N/A' if something is absent>",
      "problem": "<what is unclear, contradictory or missing>",
      "plausible_readings": ["<reading 1>", "<reading 2>"],
      "question": "<specific question the author must answer>"
    }
  ]
}

## Case B: ok
{
  "status": "ok",
  "entry_point": "<ENTRY_POINT>",
  "assumptions": [
    {
      "convention": "<standard convention or authoritative statement applied>",
      "basis": "<standard convention or the part of the description that supports it>"
    }
  ],
  "gherkin": "<the complete Gherkin feature as a single string, with \n for line breaks>"
}
Use an empty assumptions list if no convention was applied.

# Gherkin rules
- One `Feature:` named after the behavior of ENTRY_POINT, with a short description of the goal. Mention the entry point.
- Use `Background:` only for steps shared by all scenarios.
- Cover: the main success path, alternative paths, validation and error cases, and boundary values, but only where the description supports them.
- Turn each example in the description into a scenario (or an Examples row), using its exact values.
- Each scenario tests one behavior and has a specific title.
- Use Given (state), When (a single call, for example "<ENTRY_POINT> is called with ..."), Then (observable outcome). Use And/But sparingly.
- Describe inputs by business meaning and not by parameter names or types, unless the description gives them.
- Describe outcomes neutrally (for example "the result is 90.00", "an error is reported stating that...") unless the description specifies the mechanism.
- Use Scenario Outline with Examples for the same behavior with different data.
- Every Then must be observable and verifiable. Avoid "properly", "correctly", "appropriate".
- Every scenario that depends on a listed assumption must be consistent with it.
- Do not add scenarios for behavior that is not stated or clearly implied.
- Write scenario text in the language of the TASK DESCRIPTION. Keep Gherkin keywords in English.

# Self-check before answering
- Did I check every example against the stated rules?
- Did I invent any rule, value, parameter name, type, or error mechanism? If yes, remove it or switch to need_clarification.
- Is each listed assumption a standard convention or backed by the description?
- Is every Then verifiable, and is the output valid JSON in one of the two formats?

# ENTRY_POINT
{entry_point}

# TASK DESCRIPTION
{prompt}
""".strip()

GHERKIN_CODE = """You are a senior QA engineer who writes Gherkin scenarios from existing Python code.

# Goal
Given the source code of a Python function (FUNCTION_CODE), assess whether its intended behavior can be determined reliably, then do exactly one of:
- If it can: generate Gherkin scenarios for the function.
- If it cannot: return "need_clarification".

# Principles
- The code shows what the function DOES. It does not necessarily show what it SHOULD do. Scenarios must describe intended behavior, and must never encode a suspected bug as expected behavior.
- Intent is expressed by: the function name, docstring, comments, type hints, doctests/examples, and names of variables and constants. Behavior is expressed by the implementation.
- The signature, parameter names, type hints, default values, returned values, and raised exceptions are known from the code and may be used in scenarios.
- Expected outputs must be derived by tracing the code for the given inputs. Never guess a result.
- Do not invent business rules or behavior that neither the code nor its intent sources support.

# Step 1: Assess the code
Apply these checks in order. Record an issue only if it cannot be resolved by the code and its intent sources, or by the standard conventions listed in check 3.

1. Entry point (type: "entry_point")
   - Identify the function under test. If the code contains several functions, the entry point is the one that is public and not only called by the others, or the one the docstring/examples/main block exercises. Helpers are covered through it.
   - If no single entry point can be determined, record an issue.

2. Intent vs behavior (type: "contradiction")
   - Compare the implementation with the name, docstring, comments, type hints, and examples.
   - If they disagree (for example, the docstring says "inclusive" but the code uses `<`; a doctest output differs from the traced result; the return type hint differs from what is returned), record an issue.
   - Exception: if one side is clearly authoritative (for example, a precise doctest versus a loose docstring summary, supported by the other examples), treat it as resolved and list the resolution in "assumptions".

3. Ambiguity (type: "ambiguity")
   - Is the intent unclear, so that competent testers would disagree on the expected outcome? Example: no docstring and a name like `process`, or an unexplained magic number.
   - If the code is self-explanatory and standard conventions lead to one outcome, proceed and list the convention in "assumptions". Standard conventions: 0-based indexing, usual tie-breaking (first occurrence), case-sensitive comparison, natural reading of the function name.
   - Otherwise record an issue.

4. Completeness (type: "incompleteness")
   - Is the code truncated, is it a stub (`pass`, `...`, `NotImplementedError` as the only body), does it call undefined names, or contain unreachable or contradictory branches whose intended outcome is unclear?
   - Are the expected results for inputs that the code does not handle (for example `None`, empty input, negative values) unspecified in a way that cannot be settled by intent sources? Record an issue only if it affects the expected outcome of a scenario you would otherwise write. Do not write scenarios for inputs the function neither handles nor documents.

5. Testability (type: "testability")
   - Does the outcome depend on state that scenarios cannot describe or control: randomness without a seed or injectable source, current time, network, file system, environment, global or mutable module state, or external services?
   - If the dependency can be stated in Given steps (for example "the current date is 2025-01-31", "the service returns ..."), proceed and list it in "assumptions". Otherwise record an issue.

# Step 2: Decide
- If at least one issue was recorded: return "need_clarification".
- Otherwise: generate the Gherkin.
Never invent intent in order to avoid asking for clarification.

# Step 3: Respond
Return ONLY a JSON object, with no text outside it.

## Case A: need_clarification
{
  "status": "need_clarification",
  "entry_point": "<function name, or null if undetermined>",
  "reasoning": "<max 80 words>",
  "issues": [
    {
      "type": "entry_point | contradiction | ambiguity | incompleteness | testability",
      "excerpt": "<code or docstring fragment, with line reference if possible, or 'N/A'>",
      "problem": "<what is unclear, contradictory or missing>",
      "plausible_readings": ["<intended behavior 1>", "<intended behavior 2>"],
      "question": "<specific question the author must answer>"
    }
  ]
}

## Case B: ok
{
  "status": "ok",
  "entry_point": "<function name>",
  "signature": "<signature as written in the code>",
  "assumptions": [
    {
      "convention": "<standard convention, authoritative statement, or controlled dependency applied>",
      "basis": "<what supports it>"
    }
  ],
  "gherkin": "<the complete Gherkin feature as a single string, with \n for line breaks>"
}
Use an empty assumptions list if none were applied.

# Gherkin rules
- One `Feature:` named after the behavior of the function, with a short description of its purpose. Mention the function name.
- Use `Background:` only for steps shared by all scenarios.
- Cover: the main success path, alternative paths (each meaningful branch of the code), validation and error cases (including exceptions the function raises deliberately), and boundary values at the thresholds in the code, but only where intent is clear.
- Turn each docstring example or doctest into a scenario (or an Examples row), using its exact values.
- Each scenario tests one behavior and has a specific title.
- Use Given (state, including any controlled external dependency), When (a single call, for example "<function_name> is called with ..."), Then (observable outcome). Use And/But sparingly.
- Name inputs with the parameter names from the signature and give concrete values.
- Describe outcomes in terms of the return value, the exception type and message the code raises, or the side effect it performs.
- Use Scenario Outline with Examples for the same behavior with different data.
- Every expected value must be derived by tracing the code. Every Then must be observable and verifiable. Avoid "properly", "correctly", "appropriate".
- Do not write scenarios that only exercise internal implementation details (private helpers, intermediate variables).
- Do not add scenarios for behavior that is neither stated nor clearly implied.
- Write scenario text in English unless the docstring and comments are in another language, in which case use that language. Keep Gherkin keywords in English.

# Self-check before answering
- Did I trace every expected value through the code?
- Did I compare the implementation with the name, docstring, comments, hints, and examples, and flag every disagreement?
- Am I encoding a suspected bug as expected behavior? If yes, switch to need_clarification.
- Did I invent any rule or value that neither the code nor its intent sources support?
- Is each listed assumption a standard convention, backed by the code, or a stated controlled dependency?
- Is every Then verifiable, and is the output valid JSON in one of the two formats?

# FUNCTION_CODE
{code}
""".strip()


GHERKIN_COHERENT = """You are a senior QA lead who checks whether two independently derived sets of Gherkin scenarios describe the same behavior.

# Goal
You receive two Gherkin features for the same function:
- SPEC_GHERKIN: scenarios derived from the task description (what the function SHOULD do).
- CODE_GHERKIN: scenarios derived from the Python implementation (what the function DOES).

Decide whether the two sets are coherent, and do exactly one of:
- If they are coherent: return "coherent".
- If they are not: return "need_clarification".

# Principles
- Neither set is assumed correct. You do not decide which side is right. You report disagreements and ask the author.
- Compare meaning, not wording. Scenario titles, step phrasing, language, and ordering are irrelevant.
- Do not invent behavior. Use only what is in the two inputs.
- You may recompute simple expected values to check a scenario, but never rely on guesses.

# Step 1: Normalize
For every scenario, and for every row of every Scenario Outline Examples table, extract:
- Inputs: the values or conditions on the inputs. Map business terms used in SPEC_GHERKIN to the parameter names used in CODE_GHERKIN, based on the scenarios and their context. If a mapping is not clear, record an "interface_mismatch" issue.
- Controlled state: preconditions in Given steps.
- Expected outcome: the return value, reported error, or side effect.

Treat these as equivalent, not as differences:
- A neutral outcome ("an error is reported stating that X") and a concrete one (for example `ValueError` with message "X"), if the condition and meaning are the same. Note the concrete mechanism as an observation.
- Different wording, language, or ordering.
- Different representations of the same value (for example 90 and 90.00), unless the specification distinguishes them.

# Step 2: Compare
Classify each normalized scenario or row:
1. MATCH: same inputs and state, same outcome in both sets.
2. CONFLICT: same or overlapping inputs and state, different outcomes.
3. SPEC_ONLY: behavior in SPEC_GHERKIN with no corresponding behavior in CODE_GHERKIN.
4. CODE_ONLY: behavior in CODE_GHERKIN with no corresponding behavior in SPEC_GHERKIN.

Then apply these checks.

a. Conflicts (type: "conflict")
   - Report every conflict, with both excerpts and both expected outcomes.
   - Set "likely_cause" to one of: "specification_defect", "code_defect", "ambiguous_specification", "possible_generation_error", "unknown". Use "possible_generation_error" if an expected value looks wrongly derived (for example, an arithmetic mistake). Do not resolve the conflict.

b. SPEC_ONLY (type: "missing_in_code")
   - Record an issue if the specification defines an outcome that no code scenario covers and that the code scenarios do not contradict. This may indicate unimplemented behavior.
   - Do not record an issue if an equivalent code scenario or branch already covers the case.

c. CODE_ONLY (type: "undocumented_in_spec")
   - Record an issue if the code defines an outcome for inputs inside the domain the specification covers, the specification is silent, and a different outcome would also be acceptable under the specification.
   - For behavior outside the specification's domain (for example, defensive handling of invalid types), do not record an issue. List it as a non-blocking observation.

d. Interface shape (type: "interface_mismatch")
   - Compare the number and meaning of inputs, and the form of the outcome (single value, list, count, boolean, text, reported error, side effect). Record an issue if they differ in a way that changes expected outcomes, or if the mapping between the two sets cannot be established.

# Step 3: Decide
- If at least one issue was recorded: return "need_clarification".
- Otherwise: return "coherent".
- Never return "coherent" when a scenario could not be matched because of an unclear mapping. Record an issue instead.
- Non-blocking observations never cause "need_clarification".

# Step 4: Respond
Return ONLY a JSON object, with no text outside it.

## Case A: need_clarification
{
  "status": "need_clarification",
  "reasoning": "<max 80 words>",
  "issues": [
    {
      "type": "conflict | missing_in_code | undocumented_in_spec | interface_mismatch",
      "spec_excerpt": "<scenario title or step from SPEC_GHERKIN, or 'N/A'>",
      "code_excerpt": "<scenario title or step from CODE_GHERKIN, or 'N/A'>",
      "problem": "<what differs or cannot be compared>",
      "likely_cause": "specification_defect | code_defect | ambiguous_specification | possible_generation_error | unknown",
      "question": "<specific question the author must answer>"
    }
  ],
  "summary": {
    "matched": <number>,
    "conflicts": <number>,
    "spec_only": <number>,
    "code_only": <number>
  }
}

## Case B: coherent
{
  "status": "coherent",
  "reasoning": "<max 80 words>",
  "observations": [
    "<non-blocking observation, for example the concrete error mechanism used by the code, or defensive behavior not covered by the specification>"
  ],
  "summary": {
    "matched": <number>,
    "conflicts": 0,
    "spec_only": 0,
    "code_only": <number of non-blocking code-only items>
  }
}
Use an empty observations list if there are none.

# Self-check before answering
- Did I compare meaning and not wording?
- Did I examine every row of every Scenario Outline, not only the first?
- Did I report every conflict, without choosing a side?
- Did I treat neutral versus concrete outcome wording as equivalent?
- Did I avoid returning "coherent" where a mapping or comparison was unclear?
- Is the output valid JSON in one of the two formats?

# SPEC_GHERKIN
```gherkin
{gherkin_prompt}
```

# CODE_GHERKIN
```gherkin
{gherkin_code}
```"""


FIX_PROMPT = """You are a technical editor who revises programming-task descriptions.

# Goal
A task description was converted into Gherkin scenarios, and so was its Python implementation. A comparison of the two found discrepancies. Revise the TASK DESCRIPTION so that it removes every listed discrepancy.

# Principles
- The behavior shown by the implementation scenarios (CODE_GHERKIN) is the reference. Change the description to state that behavior explicitly. Do not change the behavior.
- Make the smallest edit that resolves each issue. Keep the original wording, structure, tone, and examples wherever they are not involved in an issue.
- Resolve an issue only with information found in CODE_GHERKIN or in the original description. Do not invent rules, values, or behavior.
- If an issue cannot be resolved from these sources (for example, CODE_GHERKIN is itself inconsistent, or the finding points to a code defect, so that editing the description would hide it), do not guess. Report it as unresolved.
- Do not mention Gherkin, scenarios, tests, the implementation, or the review process in the revised description. It must read as a normal task description.
- If an example in the description contradicts the corrected rule, fix the example using values from CODE_GHERKIN.
- Keep the function name and, if the original states it, the signature. If an issue shows that the number of inputs, their meaning, or the form of the output is unclear, state it explicitly.
- Write in the language of the original description.
- AUTHOR ANSWERS are authoritative and take precedence over the code and over the original description. If an answer resolves an issue, incorporate it into the description as a normal statement of the rule, and list the issue in "changes" with "AUTHOR ANSWER" as its basis. Do not mention the questions or answers in the revised description. If an answer is partial or still leaves several readings, keep the issue in "unresolved" and ask only about the remaining part.

# How to resolve each issue type
- conflict: state the rule so that it gives the outcome in CODE_GHERKIN. Correct any example that shows the other outcome.
- missing_in_code: the description claims behavior that the implementation does not have. Remove or correct that claim to match CODE_GHERKIN.
- undocumented_in_spec: add the missing rule or case, as shown in CODE_GHERKIN.
- interface_mismatch: state the inputs (number, meaning, kind) and the form of the output as shown in CODE_GHERKIN.

# Output
Return ONLY a JSON object, with no text outside it.

If every issue is resolved:
{
  "status": "fixed",
  "revised_description": "<the complete revised task description>",
  "changes": [
    {"issue": <issue number>, "change": "<what was changed and why, max 40 words>"}
  ]
}

If one or more issues cannot be resolved, still revise what can be resolved, and report the rest:
{
  "status": "partially_fixed",
  "revised_description": "<the complete revised task description, with only the resolvable issues applied>",
  "changes": [
    {"issue": <issue number>, "change": "<...>"}
  ],
  "unresolved": [
    {"issue": <issue number>, "reason": "<why it cannot be resolved from the available information>", "question": "<question for the author>"}
  ]
}

# Self-check before answering
- Does every resolved issue appear in "changes", and every other issue in "unresolved"?
- Is the revised description consistent with every scenario in CODE_GHERKIN that relates to the issues?
- Did I change anything not required by an issue?
- Did I add any rule or value that is not in CODE_GHERKIN or the original description?
- Is the output valid JSON?

# TASK DESCRIPTION
{prompt}

# AUTHOR ANSWERS
{answers}

# FINDINGS
{findings}

# CODE_GHERKIN
```gherkin
{code_gherkin}
```
"""


FIX_PROMPT_SPEC = """You are a technical editor who revises programming-task descriptions.

# Goal
A task description could not be converted into test scenarios because it is unclear, incomplete, or inconsistent. The issues found are listed in FINDINGS. Revise the TASK DESCRIPTION so that it removes every resolvable issue, using the Python implementation (FUNCTION_CODE) as the reference.

# Principles
- Make the smallest edit that resolves each issue. Keep the original wording, structure, tone, and examples wherever they are not involved in an issue. Do not rewrite statements that are not part of an issue.
- Resolve an issue only with information that can be read from FUNCTION_CODE (including its docstring and comments) or from the original description. Do not invent rules, values, or behavior.
- The code shows what the function does, not necessarily what it should do. Use it as a reference only when its behavior is clearly intentional, meaning that it is supported by its name, docstring, comments, type hints, or by the description. If the behavior looks accidental or buggy, or the code's intent is itself unclear, do not write it into the description. Report the issue as unresolved.
- Use the "plausible readings" in FINDINGS as candidates. Choose a reading only if FUNCTION_CODE supports exactly one of them. If it supports none or several, report the issue as unresolved.
- For a contradiction within the description, resolve it only if the code agrees with exactly one side. Otherwise report it as unresolved.
- For an "entry_point_mismatch" issue, do not edit. Report it as unresolved.
- Do not mention the code, the implementation, tests, Gherkin, or the review process in the revised description. It must read as a normal task description.
- If an example in the description contradicts the corrected rule, fix the example by tracing FUNCTION_CODE for the example inputs.
- Keep the function name and, if the original states it, the signature. If an issue shows that the number of inputs, their meaning, or the form of the output is unclear, state it explicitly.
- Write in the language of the original description.
- AUTHOR ANSWERS are authoritative and take precedence over the code and over the original description. If an answer resolves an issue, incorporate it into the description as a normal statement of the rule, and list the issue in "changes" with "AUTHOR ANSWER" as its basis. Do not mention the questions or answers in the revised description. If an answer is partial or still leaves several readings, keep the issue in "unresolved" and ask only about the remaining part.

# How to resolve each issue type
- incompleteness: add the missing rule, condition, edge-case behavior, or output form, as shown by the code.
- ambiguity: replace the unclear wording with an explicit statement of the reading that the code supports.
- contradiction: correct the side that the code does not support.
- interface: state the inputs (number, meaning, kind) and the form of the output, as shown by the code.

# Output
Return ONLY a JSON object, with no text outside it.

{
  "status": "fixed | partially_fixed | unfixable",
  "revised_description": "<the complete revised description; the original text if status is unfixable>",
  "changes": [
    {"issue": <issue number>, "change": "<what was changed and why, max 40 words>", "code_basis": "<the part of the code that supports it>"}
  ],
  "unresolved": [
    {"issue": <issue number>, "reason": "<why it cannot be resolved from the available information>", "question": "<question for the author>"}
  ]
}
Use "fixed" when "unresolved" is empty, "unfixable" when "changes" is empty.

# Self-check before answering
- Does every issue appear in exactly one of "changes" or "unresolved"?
- Is every change backed by a specific part of FUNCTION_CODE, and is that behavior clearly intentional?
- Did I change anything not required by an issue?
- Did I add any rule or value that is not in FUNCTION_CODE or the original description?
- Is the output valid JSON?

# TASK DESCRIPTION
{prompt}

# AUTHOR ANSWERS
{answers}

# FINDINGS
{findings}

# FUNCTION_CODE
{function_code}
"""

QUESTION_PROMPT = """You are a business analyst who asks the author of a programming-task description the minimum questions needed to remove the remaining unclear points.

# Goal
Some issues in the TASK DESCRIPTION could not be resolved automatically. Write clear questions for the author, so that their answers allow the description to be completed.

# Principles
- Ask only about the issues listed in UNRESOLVED ISSUES. Do not raise new topics.
- Do not ask what the HISTORY already answers. If an answer in HISTORY covers an issue only partially, ask only about the remaining part.
- Merge issues that depend on the same decision into one question. Ask at most 3 questions in total, ordered by how much they affect the expected outcome. If more remain, keep the most important ones.
- Each question must be self-contained, readable without seeing the review process, and answerable in one or two sentences.
- Where plausible readings exist, offer them as numbered options, using concrete input and output values from the description so that the difference is visible. Always allow a free-form answer.
- Prefer a concrete example ("For input X, should the result be A or B?") to an abstract question.
- Do not suggest which option is correct. Do not mention Gherkin, scenarios, tests, the implementation, or the review process.
- Write in the language of the TASK DESCRIPTION.

# Output
Answer ONLY with JSON: {{"question": "<text or null>"}}

# TASK DESCRIPTION
{prompt}

# UNRESOLVED ISSUES
{findings}

# HISTORY (previous questions and answers)
{history}
"""


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


from typing import Any


def _format_history(history: list[dict[str, str]]) -> str:
    if not history:
        return "None."
    return "\n".join(
        f"{i}. Q: {h.get('question', '')}\n   A: {h.get('answer', '')}"
        for i, h in enumerate(history, start=1)
    )


def _format_unresolved(
    fix_result: dict[str, Any],
    source_check: dict[str, Any],
) -> str:
    """Merge each unresolved entry with the original issue it refers to.

    source_check is the output that triggered the fixer (spec-generation
    clarification or gherkin coherence check). Issue numbers are 1-based.
    """
    source_issues = source_check.get("issues") or []
    unresolved = fix_result.get("unresolved") or []
    lines = []
    for item in unresolved:
        n = item.get("issue")
        original = source_issues[n - 1] if isinstance(n, int) and 1 <= n <= len(source_issues) else {}
        lines.append(f"Issue {n} [{original.get('type', 'unknown')}]")
        for label, key in (
            ("Description excerpt", "excerpt"),
            ("Specification scenario", "spec_excerpt"),
            ("Code scenario", "code_excerpt"),
            ("Problem", "problem"),
        ):
            if original.get(key):
                lines.append(f"- {label}: {original[key]}")
        readings = original.get("plausible_readings") or []
        if readings:
            lines.append("- Plausible readings: " + " | ".join(readings))
        lines.append(f"- Why it was not fixed: {item.get('reason', '')}")
        lines.append(f"- Draft question: {item.get('question', '')}")
        lines.append("")
    return "\n".join(lines).strip()


def _generate_question(
    env: ClarificationEnvironment,
    original_prompt: str,
    fix_result: dict[str, Any],
    source_check: dict[str, Any],
    history: list[dict[str, str]],
) -> dict[str, Any]:
    if fix_result.get("status") == "fixed":
        raise ValueError("No question needed: the fix is complete.")

    # Partial fixes are kept; for "unfixable" the fixer returns the original text.
    current_description = fix_result.get("revised_description") or original_prompt

    messages = [{
        "role": "user",
        "content": _fill(
            QUESTION_PROMPT,
            prompt=current_description,
            findings=_format_unresolved(fix_result, source_check),
            history=_format_history(history),
        ),
    }]
    return _parse_json(env.llm(messages))


def _format_findings(check: dict[str, Any]) -> str:
    issues = check.get("issues") or []
    lines = [f"Overall reasoning: {check.get('reasoning', '')}", ""]
    for i, issue in enumerate(issues, start=1):
        lines.append(f"Issue {i} [{issue.get('type', 'unknown')}]")
        if "likely_cause" in issue:
            lines.append(f"- Likely cause: {issue['likely_cause']}")
        # Coherence-check schema
        if "spec_excerpt" in issue:
            lines.append(f"- Specification scenario: {issue.get('spec_excerpt', 'N/A')}")
            lines.append(f"- Code scenario: {issue.get('code_excerpt', 'N/A')}")
        # Generation schema
        if "excerpt" in issue:
            lines.append(f"- Description excerpt: {issue.get('excerpt', 'N/A')}")
        readings = issue.get("plausible_readings") or []
        if readings:
            lines.append("- Plausible readings: " + " | ".join(readings))
        lines += [
            f"- Problem: {issue.get('problem', '')}",
            f"- Question: {issue.get('question', '')}",
            "",
        ]
    return "\n".join(lines).strip()


def _fill(template: str, **values: str) -> str:
    # Single pass, so placeholders inside inserted text are never re-substituted.
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), template)


def _fix_prompt(
    env: ClarificationEnvironment,
    prompt: str,
    gherkin_coherence_check: dict[str, Any],
    code_gherkin: str,
) -> dict[str, Any]:
    findings = _format_findings(gherkin_coherence_check)
    messages = [
        {
            "role": "user",
            "content": _fill(
                FIX_PROMPT,
                prompt=prompt,
                findings=findings,
                code_gherkin=code_gherkin,
            ),
        }
    ]
    return _parse_json(env.llm(messages))


def _fix_prompt_from_spec_clarification(
    env: ClarificationEnvironment,
    prompt: str,
    spec_clarification: dict[str, Any],
    function_code: str,
) -> dict[str, Any]:
    messages = [{
        "role": "user",
        "content": _fill(
            FIX_PROMPT_SPEC,
            prompt=prompt,
            findings=_format_findings(spec_clarification),
            function_code=function_code,
        ),
    }]
    return _parse_json(env.llm(messages))


def _generate_gherkin_scenarios(env: ClarificationEnvironment, prompt, entry_point, prompt_input: bool) -> dict[str, Any]:
    if prompt_input:
        gherkin_scenarios = GHERKIN_PROMPT.replace("{prompt}", prompt).replace(
                    "{entry_point}", entry_point)
    else:
        gherkin_scenarios = GHERKIN_CODE.replace("{code}", prompt).replace(
            "{entry_point}", entry_point)
    messages = [
        {
            "role": "user",
            "content": gherkin_scenarios,
        }
    ]
    response = env.llm(messages)
    return _parse_json(response)


def _check_coherence(env: ClarificationEnvironment, gherkin_prompt, gherkin_code) -> dict[str, Any]:
    messages = [
        {
            "role": "user",
            "content": GHERKIN_COHERENT.replace("{gherkin_prompt}", gherkin_prompt).replace(
            "{gherkin_code}", gherkin_code)
        }
    ]
    response = env.llm(messages)
    return _parse_json(response)


def _evolve_description(
    env: ClarificationEnvironment,
    description: str,
    source_check: dict[str, Any],       # the check that raised the issues
    source: str,                        # "spec_generation" or "coherence"
    history: list[dict[str, str]],      # already includes the new Q&A pair
    function_code: str | None = None,   # for spec_generation (code-assisted variant)
    code_gherkin: str | None = None,    # for coherence
) -> dict[str, Any]:
    if source == "coherence":
        template = FIX_PROMPT
        values = {"code_gherkin": code_gherkin or ""}
    else:
        template = FIX_PROMPT_SPEC
        values = {"function_code": function_code or ""}   # drop for the description-only variant

    messages = [{
        "role": "user",
        "content": _fill(
            template,
            prompt=description,
            findings=_format_findings(source_check),
            answers=_format_history(history),
            **values,
        ),
    }]
    result = _parse_json(env.llm(messages))
    if result.get("status") not in {"fixed", "partially_fixed", "unfixable"} \
            or not result.get("revised_description"):
        raise ValueError(f"Unexpected fixer output: {result}")
    return result
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


import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*(?:```|``|$)", re.DOTALL | re.IGNORECASE)

def _parse_json(text: Any) -> dict[str, Any]:
    """Extract a JSON object from a ```json block or from bare text. Always returns a dict."""
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8", errors="replace")
    if not isinstance(text, str):
        return text if isinstance(text, dict) else {}

    candidates = []

    # 1. Content of a fenced block (tolerates a missing or truncated closing fence)
    m = _FENCE_RE.search(text)
    if m:
        candidates.append(m.group(1))

    # 2. The whole text, stripped
    candidates.append(text.strip())

    # 3. Outermost {...} span in the text
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])

    for cand in candidates:
        try:
            data = json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            return data

    print("Could not parse JSON from text")
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


class LAASeR_Evolution(ClarificationAlgorithmBase):
    def run(self, env: ClarificationEnvironment, problem: dict[str, Any]) -> str:
        entry_point = problem["entry_point"]
        prompt = problem["prompt"]
        code = ""
        history = []
        retry = 10
        try:
            # Phase 1: Contrastive analysis
            while retry > 0:
                retry -= 1
                gherkin_prompt = _generate_gherkin_scenarios(env, prompt, entry_point, True)
                source = "spec_generation"
                if gherkin_prompt.get("status") != "ok":
                    source_check = gherkin_prompt
                    evolved_prompt = _fix_prompt_from_spec_clarification(env, prompt, gherkin_prompt, code)
                    if evolved_prompt.get("status") == "fixed":
                        prompt = evolved_prompt.get("revised_description")
                        continue
                code = _implement(env, prompt, entry_point)
                gherkin_code = _generate_gherkin_scenarios(env, code, entry_point, False)
                if gherkin_code.get("status") != "ok":
                    source_check = gherkin_code
                    evolved_prompt = _fix_prompt_from_spec_clarification(env, prompt, gherkin_code, code)
                    if evolved_prompt.get("status") == "fixed":
                        prompt = evolved_prompt.get("revised_description")
                        continue

                if gherkin_prompt.get("status") == "ok" and gherkin_code.get("status") == "ok":
                    equiv_check = _check_coherence(env, gherkin_prompt.get("gherkin"), gherkin_code.get("gherkin"))
                    if equiv_check.get("status") == "coherent":
                        break
                    else:
                        source_check = equiv_check
                        source = "coherence"
                        evolved_prompt = _fix_prompt(env, prompt, equiv_check, gherkin_code.get("gherkin"))
                        if evolved_prompt.get("status") == "fixed":
                            prompt = evolved_prompt.get("revised_description")
                            continue
                print("### Ask the user for clarification")
                # Ask the user for clarification
                if not env.can_ask():
                    break
                clarifying_question = _generate_question(env, prompt, evolved_prompt, source_check, history).get("question")
                if clarifying_question is None and clarifying_question == "null":
                    break
                clarification_answer = env.ask_human(clarifying_question)
                history.append({"question": clarifying_question, "answer": clarification_answer})

                fix = _evolve_description(
                    env,
                    description=prompt,
                    source_check=source_check,
                    source=source,
                    history=history,
                    function_code=code,
                    code_gherkin=gherkin_code.get("gherkin"),
                )
                prompt = fix.get("revised_description")

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
