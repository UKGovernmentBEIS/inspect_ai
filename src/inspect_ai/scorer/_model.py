import logging
import re
from collections.abc import Sequence
from functools import partial
from typing import Any, Callable

from inspect_ai._util.content import (
    Content,
    ContentAudio,
    ContentDocument,
    ContentImage,
    ContentText,
    ContentVideo,
)
from inspect_ai._util.dict import omit
from inspect_ai._util.format import format_function_call
from inspect_ai._util.list import remove_last_match_and_after
from inspect_ai._util.logger import warn_once
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._model import Model, get_model, model_roles
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._model_role import ModelRole, as_model_role
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util import resource

from ._metric import Score
from ._metrics import accuracy, stderr
from ._multi import multi_scorer
from ._reducer.types import ScoreReducer
from ._scorer import Scorer, scorer
from ._target import Target

logger = logging.getLogger(__name__)

_ModelGraderMedia = ContentImage | ContentAudio | ContentVideo | ContentDocument
_INPUT_MEDIA_TYPES: tuple[type[Content], ...] = (
    ContentImage,
    ContentAudio,
    ContentVideo,
    ContentDocument,
)

# Output/submission media is a narrower whitelist than input media -- no
# document -- matching the pre-existing `output_media` filter in
# `model_scoring_prompt`.
_OutputGraderMedia = ContentImage | ContentAudio | ContentVideo
_OUTPUT_MEDIA_TYPES: tuple[type[Content], ...] = (
    ContentImage,
    ContentAudio,
    ContentVideo,
)


@scorer(metrics=[accuracy(), stderr()])
def model_graded_fact(
    template: str | None = None,
    instructions: str | None = None,
    grade_pattern: str | None = None,
    include_history: bool | Callable[[TaskState], str] = False,
    partial_credit: bool = False,
    model: list[str | Model] | str | Model | None = None,
    model_role: str | ModelRole | None = "grader",
    reducer: str | ScoreReducer = "majority",
) -> Scorer:
    """Score a question/answer task with a fact response using a model.

    Args:
      template: Template for grading prompt. This template uses
        four variables: `question`, `criterion`, `answer`, and
        `instructions` (which is fed from the `instructions` parameter).
        Variables from sample `metadata` are also available in the template.
      instructions: Grading instructions. This should
        include a prompt for the model to answer (e.g. with
        with chain of thought reasoning) in a way that matches
        the specified `grade_pattern`, for example, the default
        `grade_pattern` looks for one of GRADE: C, GRADE: P, or
        GRADE: I).
      grade_pattern: Regex to extract the grade from the
        model response. Defaults to looking for e.g. GRADE: C
        The regex should have a single capture group that
        extracts exactly the letter C, P, or I.
      include_history:
        Whether to include the full chat history in the presented
        question. Defaults to `False`, which presents only the
        original sample input. Optionally provide a function to
        customise how the chat history is presented.
      partial_credit: Whether to allow for "partial" credit for
         answers (by default assigned a score of 0.5). Defaults
         to `False`. Only used with the default `instructions`
         (as custom instructions provide their own prompts for
         grades). Under those defaults the grader is offered
         C/I, or C/P/I when this is `True`, and its final
         `GRADE:` verdict is validated against that set: a
         verdict outside it (a `P` that was never offered, or
         any other letter) is a grade-parse failure and leaves
         the sample unscored rather than being scored or
         silently falling back to an earlier grade mentioned in
         the reasoning. Custom `instructions` or an explicit
         `grade_pattern` are authoritative and keep every grade
         they match.
      model: Model or models to use for grading. If a list is provided,
        each model grades independently and the grades are combined by
        `reducer`. When this parameter is provided, it takes precedence
        over `model_role`.
      model_role: Named model role to use for grading (default: "grader").
        Pass `ModelRole(name, required=True)` to require a model to be bound
        to the role. Ignored if `model` is provided. If specified and a model
        is bound to this role (e.g. via the `model_roles` argument to `eval()`),
        that model is used. If a list of models is bound to this role, each
        model grades independently and the grades are combined by `reducer`
        (as when a list is passed for `model`). If no role-bound model is
        available and the role is not required, the model being evaluated (the
        default model) is used.
      reducer: How the grades of a grader panel are combined (used when
        `model` — or the binding of `model_role` — is a list). Defaults to
        `"majority"`: a grade must be returned by more than half of the
        graders, and the sample is unscored otherwise, so a grader that
        returns no parseable grade withholds a vote rather than shrinking the
        panel. Pass `"mode"` for the previous behaviour, in which the most
        common grade wins and a tie is broken by the order of `model`.
    """
    return _model_graded_scorer(
        template=template,
        default_template=DEFAULT_MODEL_GRADED_FACT_TEMPLATE,
        instructions=instructions,
        grade_pattern=grade_pattern,
        include_history=include_history,
        partial_credit=partial_credit,
        model=model,
        model_role=model_role,
        reducer=reducer,
    )


@scorer(metrics=[accuracy(), stderr()])
def model_graded_qa(
    template: str | None = None,
    instructions: str | None = None,
    grade_pattern: str | None = None,
    include_history: bool | Callable[[TaskState], str] = False,
    partial_credit: bool = False,
    model: list[str | Model] | str | Model | None = None,
    model_role: str | ModelRole | None = "grader",
    reducer: str | ScoreReducer = "majority",
) -> Scorer:
    """Score a question/answer task using a model.

    Args:
      template: Template for grading prompt. This template has
        four variables:
           - `question`, `criterion`, `answer`, and
        `instructions` (which is fed from the `instructions` parameter).
        Variables from sample `metadata` are also available in the template.
      instructions: Grading instructions. This should
        include a prompt for the model to answer (e.g. with
        with chain of thought reasoning) in a way that matches
        the specified `grade_pattern`, for example, the default
        `grade_pattern` looks for one of GRADE: C, GRADE: P, or
        GRADE: I.
      grade_pattern: Regex to extract the grade from the
        model response. Defaults to looking for e.g. GRADE: C
        The regex should have a single capture group that
        extracts exactly the letter C, P, I.
      include_history:
        Whether to include the full chat history in the presented
        question. Defaults to `False`, which presents only the
        original sample input. Optionally provide a function to
        customise how the chat history is presented.
      partial_credit: Whether to allow for "partial" credit for
        answers (by default assigned a score of 0.5). Defaults
        to `False`. Only used with the default `instructions`
        (as custom instructions provide their own prompts for
        grades). Under those defaults the grader is offered
        C/I, or C/P/I when this is `True`, and its final
        `GRADE:` verdict is validated against that set: a
        verdict outside it (a `P` that was never offered, or
        any other letter) is a grade-parse failure and leaves
        the sample unscored rather than being scored or
        silently falling back to an earlier grade mentioned in
        the reasoning. Custom `instructions` or an explicit
        `grade_pattern` are authoritative and keep every grade
        they match.
      model: Model or models to use for grading. If a list is provided,
        each model grades independently and the grades are combined by
        `reducer`. When this parameter is provided, it takes precedence
        over `model_role`.
      model_role: Named model role to use for grading (default: "grader").
        Pass `ModelRole(name, required=True)` to require a model to be bound
        to the role. Ignored if `model` is provided. If specified and a model
        is bound to this role (e.g. via the `model_roles` argument to `eval()`),
        that model is used. If a list of models is bound to this role, each
        model grades independently and the grades are combined by `reducer`
        (as when a list is passed for `model`). If no role-bound model is
        available and the role is not required, the model being evaluated (the
        default model) is used.
      reducer: How the grades of a grader panel are combined (used when
        `model` — or the binding of `model_role` — is a list). Defaults to
        `"majority"`: a grade must be returned by more than half of the
        graders, and the sample is unscored otherwise, so a grader that
        returns no parseable grade withholds a vote rather than shrinking the
        panel. Pass `"mode"` for the previous behaviour, in which the most
        common grade wins and a tie is broken by the order of `model`.
    """
    return _model_graded_scorer(
        template=template,
        default_template=DEFAULT_MODEL_GRADED_QA_TEMPLATE,
        instructions=instructions,
        grade_pattern=grade_pattern,
        include_history=include_history,
        partial_credit=partial_credit,
        model=model,
        model_role=model_role,
        reducer=reducer,
    )


def _model_graded_scorer(
    *,
    template: str | None,
    default_template: str,
    instructions: str | None,
    grade_pattern: str | None,
    include_history: bool | Callable[[TaskState], str],
    partial_credit: bool,
    model: list[str | Model] | str | Model | None,
    model_role: str | ModelRole | None,
    reducer: str | ScoreReducer,
) -> Scorer:
    """Shared implementation behind the public ``model_graded_qa``/``model_graded_fact`` factories.

    ``is_standard_template`` records whether the caller left ``template``
    unset -- i.e. this scorer is using one of the two known built-in
    templates -- decided once here, explicitly, rather than by inspecting
    template text later. It unlocks placing ordered question/submission
    content directly in the template's data slots (see
    ``model_scoring_prompt``); custom templates keep the original
    text-plus-labeled-attachment behavior instead.
    """
    is_standard_template = template is None

    # resolve a file/resource template to its content now, at factory time:
    # the deferred fan-out path below constructs its sub-scorers at scoring
    # time, when the CWD may no longer be the task directory a relative
    # template path was meant to resolve against (and `resource()` would then
    # silently treat the missing path as literal template content)
    grading_template = resource(template if template else default_template)

    # bind variables
    get_scorer = partial(
        _model_graded_qa_single,
        grading_template,
        is_standard_template,
        instructions,
        grade_pattern,
        include_history,
        partial_credit,
    )

    # an explicit model takes precedence over model_role (documented); when
    # the role is required, the caller asked for a hard prerequisite that is
    # silently bypassed, so surface it at construction time. warn_once dedups
    # on the message text, so independent bypasses sharing a role name (across
    # scorers or models) report once per process — one signal is enough for
    # the caller to change the pattern.
    if model is not None and model_role is not None:
        role = as_model_role(model_role)
        if role.required:
            warn_once(
                logger,
                f"model_graded scorer: an explicit 'model' is provided, so the "
                f"required '{role.name}' role will not be consulted",
            )

    # explicit model(s): a list grades by majority vote
    if isinstance(model, list):
        return multi_scorer([get_scorer(m) for m in model], reducer)
    if model is not None:
        return get_scorer(model)

    # no role in play: grade with the default model
    if model_role is None:
        return get_scorer(None)

    # a model_role is in play, and its binding (a single model or a list of
    # models, e.g. via the `model_roles` argument to `eval()`) isn't knowable
    # here -- tasks and their scorers are typically constructed before `eval()`
    # binds roles -- so resolve it at scoring time: fan out to a grader per
    # role-bound model (majority vote) when the role is bound to a list
    role = as_model_role(model_role)

    async def score(state: TaskState, target: Target) -> Score | None:
        role_models = model_roles().get(role.name)
        if isinstance(role_models, list):
            graders = [get_scorer(m) for m in role_models]
            return await multi_scorer(graders, reducer)(state, target)
        grader = get_model(role=role.name, required=role.required)
        return await get_scorer(grader)(state, target)

    return score


@scorer(metrics=[accuracy(), stderr()])
def _model_graded_qa_single(
    grading_template: str,
    is_standard_template: bool,
    instructions: str | None = None,
    grade_pattern: str | None = None,
    include_history: bool | Callable[[TaskState], str] = False,
    partial_credit: bool = False,
    model: str | Model | None = None,
) -> Scorer:
    # returns a scorer that does model graded qa for a single model (None =
    # the default model being evaluated). `grading_template` is resolved
    # template *content* and all model/role precedence has been applied --
    # `model_graded_qa` resolves both (see comments there)

    # resolve instructions and grade_pattern
    using_default_instructions = not instructions
    instructions = (
        instructions if instructions else default_instructions(partial_credit)
    )
    default_grade_pattern = grade_pattern is None
    # We only know which grades the grader was actually offered when *we* wrote
    # the instructions; custom `instructions` carry their own prompt and an
    # explicit `grade_pattern` is authoritative, so both are exempt and keep
    # every grade their pattern matches.
    validate_offered_grades = default_grade_pattern and using_default_instructions
    offered_grades = ("C", "P", "I") if partial_credit else ("C", "I")
    # Validating after the match -- rather than narrowing the pattern's
    # character class -- is what keeps the final verdict authoritative. The
    # pattern's leading greedy ".*" binds to the last "GRADE: X" in the
    # completion; a narrower class would make an off-menu verdict backtrack onto
    # an earlier mention in the chain of thought and score that instead, which
    # is exactly the injection vector the last-match binding exists to close.
    resolved_grade_pattern = (
        _PERMISSIVE_GRADE_PATTERN
        if validate_offered_grades
        else (grade_pattern or DEFAULT_GRADE_PATTERN)
    )

    async def score(state: TaskState, target: Target) -> Score:
        # resolve model
        nonlocal model
        model = model if isinstance(model, Model) else get_model(model)

        # metadata without grading template variables
        metadata = omit(
            state.metadata, ["question", "answer", "criterion", "instructions"]
        )

        # Original-input media is always sourced from the immutable
        # `state.input`, independent of which text is selected below for
        # `question` -- a mutable/compacted `state.messages` under
        # `include_history=True` can't drop or replace it, and an earlier
        # user turn's media isn't lost just because a later turn supplies
        # the presented question text.
        input_media = _model_grader_input_media(state.input)
        input_media_text = " ".join(f"[{media.type}]" for media in input_media)

        # `input_content` is the ordered content (text and media, in
        # original order) that backs [Task media]/data-slot reconstruction.
        # It is `None` only for a callable `include_history`, whose returned
        # string has no structure to interleave media back into.
        input_content: list[Content] | None
        if include_history is True:
            question = chat_history(state)
            if (
                input_media_text
                and isinstance(state.input, list)
                and not any(
                    isinstance(message, ChatMessageUser) and message.text
                    for message in state.input
                )
            ):
                question = f"{input_media_text}{question}"
            # Reuse chat_history's own formatting (User/Assistant/Tool
            # labels, tool call arguments) rather than re-flattening
            # `state.messages` -- that keeps role boundaries and tool-call
            # information intact -- then append the original-input media
            # independently, so it survives even when `state.messages` (e.g.
            # after compaction) no longer resembles `state.input` at all.
            history_content: list[Content] = (
                [ContentText(text=question)] if question else []
            )
            history_content.extend(input_media)
            input_content = history_content
        elif callable(include_history):
            # a custom callback already returns a flattened string with no
            # structure to interleave media back into, and its own text
            # selection isn't knowable, so [Task media] stays a bare media
            # list sourced from the original sample input (documented
            # fallback) -- reconstructing captions here could reintroduce
            # text the callback intentionally excluded.
            question = include_history(state)
            input_content = None
        else:
            input_content = _default_task_content(state.input)
            try:
                question = state.input_text
            except ValueError:
                if (
                    not input_media
                    or not isinstance(state.input, list)
                    or not any(
                        isinstance(message, ChatMessageUser) for message in state.input
                    )
                ):
                    raise
                question = ""
        if not question and input_media_text and not callable(include_history):
            question = input_media_text

        # format the scoring template
        scoring_prompt = model_scoring_prompt(
            template=grading_template,
            question=question,
            output=state.output,
            criterion=target.text,
            instructions=instructions,
            metadata=metadata,
            input_media=input_media,
            input_content=input_content,
            is_standard_template=is_standard_template,
        )

        # query the model for the score
        result = await model.generate([scoring_prompt])
        metadata_prompt = _model_grading_metadata_message(scoring_prompt)
        metadata_response = _model_grading_metadata_message(result.message)

        # extract the grade
        match = re.search(resolved_grade_pattern, result.completion)
        value = match.group(1) if match else None
        if value is not None and default_grade_pattern:
            # The permissive capture takes the whole word so that "GRADE:
            # Correct"/"GRADE: Incorrect"/"GRADE: Partial" keep resolving to
            # their letter. A multi-character verdict that is not one of the
            # spelled-out grades (e.g. "GRADE: CI") is a protocol deviation,
            # not evidence about the submission, so it is a parse failure
            # rather than a silently laundered first letter.
            normalized = value.strip().lower()
            if normalized in _GRADE_WORD_VALUES:
                value = _GRADE_WORD_VALUES[normalized]
            elif len(value.strip()) == 1:
                value = value.strip().upper()
            else:
                value = None
            if validate_offered_grades and value not in offered_grades:
                # A verdict outside the grades the instructions offered is a
                # protocol deviation, not evidence about the submission, so it
                # is a scoring failure rather than an incorrect answer.
                value = None
        if value is not None:
            return Score(
                value=value,
                answer=state.output.completion,
                explanation=result.completion,
                metadata=dict(
                    grading=[
                        metadata_prompt,
                        metadata_response,
                    ]
                ),
            )
        else:
            return Score.unscored(
                reason="grader_failed",
                answer=state.output.completion,
                explanation="Grade not found in model output: "
                + f"{result.completion}",
                metadata=dict(
                    grading=[
                        metadata_prompt,
                        metadata_response,
                    ],
                ),
            )

    return score


# these templates are based on the openai closedqa templates here:
# https://github.com/openai/evals/blob/main/evals/registry/modelgraded/closedqa.yaml
DEFAULT_MODEL_GRADED_QA_TEMPLATE = """
You are assessing a submitted answer on a given task based on a criterion. Here is the data:

[BEGIN DATA]
***
[Task]: {question}
***
[Submission]: {answer}
***
[Criterion]: {criterion}
***
[END DATA]

Does the submission meet the criterion?

{instructions}
"""

DEFAULT_MODEL_GRADED_FACT_TEMPLATE = """
You are comparing a submitted answer to an expert answer on a given question. Here is the data:

[BEGIN DATA]
************
[Question]: {question}
************
[Expert]: {criterion}
************
[Submission]: {answer}
************
[END DATA]

Compare the factual content of the submitted answer with the expert answer. Ignore any differences in style, grammar, or punctuation.

Does the submission contain the content in the expert answer?

{instructions}
"""


def default_instructions(partial_credit: bool) -> str:
    partial_letter = "P" if partial_credit else ""
    partial_prompt = '"P" for partially correct answers,' if partial_credit else ""
    return f"""
After assessing the submitted answer, reply with 'GRADE: $LETTER' (without quotes) where LETTER is one of C{partial_letter}I.  Please choose ONE option for the grade: either "C" for correct answers, {partial_prompt}or "I" for incorrect answers.

For example, after reviewing a correct answer you might write 'GRADE: C' or after reviewing an incorrect answer you might write 'GRADE: I'.

First, write out in a step by step manner your reasoning about the criterion to be sure that your conclusion is correct. Avoid simply stating the correct answers at the outset. Then, end with your answer formatted as 'GRADE: $LETTER' (without quotes) where LETTER is one of C{partial_letter}I.
"""


# Whitespace plus zero-width / formatting marks that can appear around a
# verdict separator in model output or pasted text.
_GRADE_SPACING = r"[\s\u200b\u200c\u200d\u200e\u200f\u2060\u2063\ufeff]*"

# Spelled-out verdicts the default instructions may elicit, mapped to their
# single-letter grade. Anything else multi-character is a parse failure.
_GRADE_WORD_VALUES = {
    "c": "C",
    "correct": "C",
    "i": "I",
    "incorrect": "I",
    "p": "P",
    "partial": "P",
}

DEFAULT_GRADE_PATTERN = (
    rf"(?is).*(?<!\w)GRADE(?!\w){_GRADE_SPACING}:{_GRADE_SPACING}([CPI])"
)
"""Regex to extract the grade from the COT above.

The leading greedy ``.*`` (with DOTALL) ensures ``re.search`` binds to the
*last* ``GRADE: X`` in the grader output — the instructions tell the grader
to end with the grade, so earlier mentions (e.g. echoed in chain-of-thought
or injected via the submission) must not win. The ``GRADE`` token is bounded so
ordinary prose like ``downgrade:`` cannot be mistaken for a verdict. No
end-of-string anchor is used so that trailing text after the grade line does
not suppress the match.

Used when a custom ``instructions`` prompt is in play, where the grades on
offer are unknown; with the default instructions the scorer uses a permissive
capture and validates the verdict against the grades those instructions
actually offered (see ``model_graded_qa``).
"""

# Same as DEFAULT_GRADE_PATTERN but capturing whatever word follows the
# separator instead of only ``[CPI]``. Used with the default instructions,
# where the offered grades are known and the verdict can be validated after the
# match. A ``*`` quantifier (not ``+``) so the capture can never fail and force
# the leading greedy ``.*`` to backtrack onto an earlier ``GRADE: X``: the final
# verdict decides the score, and an unusable one is a parse failure rather than
# a licence to score some mention from the chain of thought.
_PERMISSIVE_GRADE_PATTERN = (
    rf"(?is).*(?<!\w)GRADE(?!\w){_GRADE_SPACING}:{_GRADE_SPACING}(\w*)"
)


def _history_messages(state: TaskState) -> list[ChatMessage]:
    """Messages ``chat_history`` renders.

    History minus system turns, up to and including the final assistant turn
    (anything after it is dropped). Exposed separately so callers
    reconstructing ``[Task media]`` for ``include_history=True`` select from
    exactly the same messages that produced the presented question text.
    """
    # filter out system messages
    messages: list[ChatMessage] = [
        message
        for message in state.messages
        if not isinstance(message, ChatMessageSystem)
    ]

    # present message history through the final assistant turn. The default
    # templates also include state.output.completion in the Submission slot.
    return remove_last_match_and_after(
        messages, lambda message: isinstance(message, ChatMessageAssistant)
    )


def chat_history(state: TaskState) -> str:
    messages = _history_messages(state)

    # begin history with text of first message (it will come right after
    # 'Task' or 'Question' in the template)
    history: list[str] = []
    if len(messages) > 0:
        history.append(messages[0].text)

        # for subsequent messages present with e.g. Assistant: {message.text}
        for message in messages[1:]:
            if isinstance(message, ChatMessageUser):
                history.append(f"User: {message.text}")
            elif isinstance(message, ChatMessageAssistant):
                assistant_message = [message.text] if message.text else []
                if message.tool_calls:
                    assistant_message.extend(
                        [
                            format_function_call(
                                tool_call.function, tool_call.arguments
                            )
                            for tool_call in message.tool_calls
                        ]
                    )
                history.append("Assistant: " + "\n\n".join(assistant_message))
            elif isinstance(message, ChatMessageTool):
                history.append(
                    f"Tool ({message.function}): {message.tool_error or ''}{message.text}"
                )

    return "\n\n".join(history)


# Structural delimiters used in the default grading templates. Literal space (not
# \s) is intentional — \s also matches U+00A0 (NBSP), which would let a model
# pre-neutralize its own output and bypass the mitigation.
_STRUCTURAL_DELIMITER_RE = re.compile(r"\[(BEGIN|END) DATA\]", re.IGNORECASE)


def neutralize_structural_delimiters(text: str) -> str:
    """Neutralize ``[BEGIN DATA]``/``[END DATA]`` to prevent judge prompt injection.

    Replaces the space with a dash (``[END-DATA]``) so the marker is distinct
    from the template's own structural tokens. Idempotent — the dash form
    cannot match the pattern.
    """
    return _STRUCTURAL_DELIMITER_RE.sub(lambda m: m.group(0).replace(" ", "-"), text)


def _sanitize_metadata_value(v: Any) -> Any:
    # Recursively sanitize string leaves while preserving container structure so
    # that {ctx[key]} subscript access and typed format specs still work.
    if isinstance(v, str):
        return neutralize_structural_delimiters(v)
    elif isinstance(v, dict):
        return {k: _sanitize_metadata_value(val) for k, val in v.items()}
    elif isinstance(v, list):
        return [_sanitize_metadata_value(item) for item in v]
    elif isinstance(v, tuple):
        return tuple(_sanitize_metadata_value(item) for item in v)
    else:
        return v


def model_scoring_prompt(
    *,
    template: str,
    question: str,
    output: ModelOutput,
    criterion: str,
    instructions: str,
    metadata: dict[str, Any],
    input_media: Sequence[_ModelGraderMedia] = (),
    input_content: Sequence[Content] | None = None,
    is_standard_template: bool = False,
) -> ChatMessageUser:
    # Neutralize structural delimiters in all dataset-controlled inputs so a model
    # cannot inject fake [END DATA] / [BEGIN DATA] markers into the judge prompt.
    # `instructions` is author-controlled and intentionally left as-is.
    answer = neutralize_structural_delimiters(output.completion)
    question = neutralize_structural_delimiters(question)
    criterion = neutralize_structural_delimiters(criterion)
    sanitized_metadata: dict[str, Any] = {
        k: _sanitize_metadata_value(v) for k, v in metadata.items()
    }

    # we need to remove media objects from output and reference them as attachements in the answer
    output_content: list[Content] = (
        list(output.message.content)
        if len(output.choices) > 0 and isinstance(output.message.content, list)
        else []
    )
    output_media: list[Content] = [
        content
        for content in output_content
        if content.type in ["image", "audio", "video"]
    ]

    # One of the two known built-in templates: place ordered question/
    # submission content directly in their `{question}`/`{answer}` data
    # slots, ahead of the template's closing boundary and instructions,
    # rather than a trailing reconstruction the grader has to relate back
    # to a pointer.
    if is_standard_template and (len(input_media) > 0 or len(output_media) > 0):
        return _standard_template_prompt(
            template=template,
            question=question,
            answer=answer,
            criterion=criterion,
            instructions=instructions,
            sanitized_metadata=sanitized_metadata,
            input_media=input_media,
            input_content=input_content,
            output_media=output_media,
            output_content=output_content,
        )

    # Compatible labeled-attachment fallback for custom templates (and
    # standard templates with no media): keeps `question`/`answer` as real
    # text -- preserving existing string-formatting semantics, including
    # format specs like `{question:.4}` -- and attaches media as a separate
    # labeled block instead of reconstructing the field itself.
    if len(input_media) > 0:
        question = (
            f"{question} (see [Task media])"
            if len(question) > 0
            else "See [Task media]"
        )
    if len(output_media) > 0:
        answer = (
            f"{answer} (see [Submission media])"
            if len(answer) > 0
            else "See [Submission media]"
        )

    # format the prompt
    prompt = template.format(
        question=question,
        answer=answer,
        criterion=criterion,
        instructions=instructions,
        **sanitized_metadata,
    )

    # return with media if necessary
    if len(input_media) > 0 or len(output_media) > 0:
        content: list[Content] = [ContentText(text=prompt)]
        if len(input_media) > 0:
            content.append(ContentText(text="[Task media]"))
            content.extend(
                _media_block_content(input_media, input_content, _INPUT_MEDIA_TYPES)
            )
        if len(output_media) > 0:
            content.append(ContentText(text="[Submission media]"))
            content.extend(
                _media_block_content(output_media, output_content, _OUTPUT_MEDIA_TYPES)
            )
        return ChatMessageUser(content=content)
    else:
        return ChatMessageUser(content=prompt)


def _standard_template_prompt(
    *,
    template: str,
    question: str,
    answer: str,
    criterion: str,
    instructions: str,
    sanitized_metadata: dict[str, Any],
    input_media: Sequence[Content],
    input_content: Sequence[Content] | None,
    output_media: Sequence[Content],
    output_content: Sequence[Content],
) -> ChatMessageUser:
    """Build the grading prompt for a built-in (standard) template.

    Splits the template at its literal ``{question}``/``{answer}`` tokens --
    safe only because both built-in templates are known not to apply format
    specs to these fields -- and places each slot's ordered content
    (admissible media plus its own text, in original order) directly
    between the surrounding template text, ahead of the closing data
    boundary and grading instructions. This is deliberately not a general
    template engine: a custom template goes through the labeled-attachment
    fallback in ``model_scoring_prompt`` instead, since it may apply format
    specs or repeat/reorder these fields in ways this split can't handle.
    """
    before_question, _, rest = template.partition("{question}")
    between, _, after_answer = rest.partition("{answer}")

    def fmt(segment: str) -> str:
        return segment.format(
            criterion=criterion, instructions=instructions, **sanitized_metadata
        )

    content: list[Content] = []
    before_question = fmt(before_question)
    if before_question:
        content.append(ContentText(text=before_question))
    content.extend(
        _standard_slot_content(question, input_media, input_content, _INPUT_MEDIA_TYPES)
    )
    between = fmt(between)
    if between:
        content.append(ContentText(text=between))
    content.extend(
        _standard_slot_content(
            answer, output_media, output_content, _OUTPUT_MEDIA_TYPES
        )
    )
    after_answer = fmt(after_answer)
    if after_answer:
        content.append(ContentText(text=after_answer))
    return ChatMessageUser(content=content)


def _standard_slot_content(
    text: str,
    media: Sequence[Content],
    ordered_content: Sequence[Content] | None,
    admissible_media: tuple[type[Content], ...],
) -> list[Content]:
    """Ordered content for one ``{question}``/``{answer}`` data slot.

    With the original interleaved content available, reproduces it verbatim
    -- unconditionally, not gated on how many text runs it contains -- so
    the slot occupies its template position exactly as authored. Without it
    (a callable ``include_history``, whose returned string has no structure
    to interleave media back into), falls back to the flat text followed by
    the media, in original order.
    """
    if not media:
        return [ContentText(text=text)] if text else []
    if ordered_content is not None:
        return _ordered_admissible_content(ordered_content, admissible_media)
    content: list[Content] = [ContentText(text=text)] if text else []
    content.extend(media)
    return content


def _ordered_admissible_content(
    ordered_content: Sequence[Content],
    admissible_media: tuple[type[Content], ...],
) -> list[Content]:
    """Reproduce ``ordered_content`` verbatim -- admissible media plus neutralized, non-blank text, in original order.

    Text is neutralized here, on a copy, rather than mutating the original
    ``Content``, so a reconstructed caption can't smuggle raw structural
    delimiters into the grader prompt. Content outside ``admissible_media``
    (e.g. reasoning, tool-use) is dropped, since this reconstruction lands
    in a grader **user** message that can't carry it.
    """
    result: list[Content] = []
    for item in ordered_content:
        if isinstance(item, ContentText):
            text = neutralize_structural_delimiters(item.text)
            if text.strip():
                result.append(ContentText(text=text))
        elif isinstance(item, admissible_media):
            result.append(item)
    return result


def _media_block_content(
    media: Sequence[Content],
    ordered_content: Sequence[Content] | None,
    admissible_media: tuple[type[Content], ...],
) -> list[Content]:
    """Content for a ``[Task media]``/``[Submission media]`` labeled-attachment block.

    Media introduced by a single caption (one text run followed by one or
    more media items) is unambiguous once paired with that caption, already
    present in the surrounding question/answer text -- so the block stays
    the bare admissible-media list, in original order. Multiple *distinct*
    captions each introducing their own media lose that correspondence once
    flattened into a trailing list, so when the original interleaved
    content is available the block instead reproduces it verbatim -- see
    ``_ordered_admissible_content``. Without ordered content (a custom
    ``include_history`` callback, or a direct ``model_scoring_prompt``
    caller that only supplies ``media``) the block is the bare media list,
    in original order.
    """
    if ordered_content is None:
        return list(media)
    text_runs = [
        content
        for content in ordered_content
        if isinstance(content, ContentText) and content.text.strip()
    ]
    if len(text_runs) <= 1:
        return list(media)
    return _ordered_admissible_content(ordered_content, admissible_media)


def _model_grading_metadata_message(message: ChatMessage) -> ChatMessage:
    if isinstance(message.content, list) and any(
        isinstance(content, _ModelGraderMedia) for content in message.content
    ):
        return message.model_copy(update={"content": message.text})
    return message


def _final_input_user_message(
    sample_input: str | list[ChatMessage],
) -> ChatMessage | None:
    """The message backing ``TaskState.input_text`` under ``include_history=False``.

    Selecting from this same message keeps ``[Task media]`` reconstruction
    aligned with the presented question: content from an earlier turn, or
    from another role, in a multi-message sample input can't leak in just
    because it happens to sit somewhere in ``state.input``.
    """
    if isinstance(sample_input, str):
        return None
    return next(
        (
            message
            for message in reversed(sample_input)
            if isinstance(message, ChatMessageUser)
        ),
        None,
    )


def _default_task_content(sample_input: str | list[ChatMessage]) -> list[Content]:
    """Ordered content for the default (``include_history=False``) data slot.

    Keeps the final user message's own text/media interleaving intact --
    it backs ``TaskState.input_text``, the presented question -- and adds
    any other original-input message's media so an earlier turn's
    reference isn't dropped, without reintroducing that other message's
    text, which the presented question intentionally omits.
    """
    if isinstance(sample_input, str):
        return []
    final_message = _final_input_user_message(sample_input)
    content: list[Content] = []
    for message in sample_input:
        if message is final_message:
            content.extend(
                [ContentText(text=message.content)]
                if isinstance(message.content, str)
                else list(message.content)
            )
        elif isinstance(message.content, list):
            content.extend(
                item for item in message.content if isinstance(item, _ModelGraderMedia)
            )
    return content


def _model_grader_input_content(
    sample_input: str | list[ChatMessage],
) -> list[Content]:
    """Original sample-input content (text and media), all roles.

    In original message/content order. Used only as the documented
    ``include_history`` callback fallback (see
    ``_media_block_content``): an arbitrary callback's own text selection
    isn't knowable, so its ``[Task media]`` block is media-only, sourced from
    the whole original input regardless of role.
    """
    if isinstance(sample_input, str):
        return []
    return [
        content
        for message in sample_input
        if isinstance(message.content, list)
        for content in message.content
    ]


def _model_grader_input_media(
    sample_input: str | list[ChatMessage],
) -> list[_ModelGraderMedia]:
    return [
        content
        for content in _model_grader_input_content(sample_input)
        if isinstance(
            content, ContentImage | ContentAudio | ContentVideo | ContentDocument
        )
    ]
