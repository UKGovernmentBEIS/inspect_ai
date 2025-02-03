import re
from functools import partial
from typing import Callable

from inspect_ai._util.dict import omit
from inspect_ai._util.format import format_function_call
from inspect_ai._util.list import remove_last_match_and_after
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._model import Model, get_model
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util import resource

from ._metric import INCORRECT, Score
from ._metrics import accuracy, stderr
from ._multi import multi_scorer
from ._scorer import Scorer, scorer
from ._target import Target


@scorer(metrics=[accuracy(), stderr()])
def model_graded_fact(
    template: str | None = None,
    instructions: str | None = None,
    grade_pattern: str | None = None,
    include_history: bool | Callable[[TaskState], str] = False,
    partial_credit: bool = False,
    model: list[str | Model] | str | Model | None = None,
) -> Scorer:
    """Score a question/answer task with a fact response using a model.

    Args:
      template (str): Template for grading prompt. This template uses
        four variables: `question`, `criterion`, `answer`, and
        `instructions` (which is fed from the `instructions` parameter).
        Variables from sample `metadata` are also available in the template.
      instructions (str): Grading instructions. This should
        include a prompt for the model to answer (e.g. with
        with chain of thought reasoning) in a way that matches
        the specified `grade_pattern`, for example, the default
        `grade_pattern` looks for one of GRADE: C, GRADE: P, or
        GRADE: I).
      grade_pattern (str): Regex to extract the grade from the
        model response. Defaults to looking for e.g. GRADE: C
        The regex should have a single capture group that
        extracts exactly the letter C, P, or I.
      include_history (bool | Callable[[TaskState], str]):
        Whether to include the full chat history in the presented
        question. Defaults to `False`, which presents only the
        original sample input. Optionally provide a function to
        customise how the chat history is presented.
      partial_credit (bool): Whether to allow for "partial" credit for
         answers (by default assigned a score of 0.5). Defaults
         to `False`. Note that this parameter is only used
         with the default `instructions` (as custom instructions
         provide their own prompts for grades).
      model (list[str | Model] | str | Model | None): Model or Models to use for grading. If multiple models are passed, a majority vote of their grade will be returned. By default the model being evaluated is used.
    """
    return model_graded_qa(
        template=template if template else DEFAULT_MODEL_GRADED_FACT_TEMPLATE,
        instructions=instructions,
        grade_pattern=grade_pattern,
        include_history=include_history,
        partial_credit=partial_credit,
        model=model,
    )


@scorer(metrics=[accuracy(), stderr()])
def model_graded_qa(
    template: str | None = None,
    instructions: str | None = None,
    grade_pattern: str | None = None,
    include_history: bool | Callable[[TaskState], str] = False,
    partial_credit: bool = False,
    model: list[str | Model] | str | Model | None = None,
) -> Scorer:
    """Score a question/answer task using a model.

    Args:
      template (str): Template for grading prompt. This template has
        four variables:
           - `question`, `criterion`, `answer`, and
        `instructions` (which is fed from the `instructions` parameter).
        Variables from sample `metadata` are also available in the template.
      instructions (str): Grading instructions. This should
        include a prompt for the model to answer (e.g. with
        with chain of thought reasoning) in a way that matches
        the specified `grade_pattern`, for example, the default
        `grade_pattern` looks for one of GRADE: C, GRADE: P, or
        GRADE: I.
      grade_pattern (str): Regex to extract the grade from the
        model response. Defaults to looking for e.g. GRADE: C
        The regex should have a single capture group that
        extracts exactly the letter C, P, I.
      include_history (bool | Callable[[TaskState], str]):
        Whether to include the full chat history in the presented
        question. Defaults to `False`, which presents only the
        original sample input. Optionally provide a function to
        customise how the chat history is presented.
      partial_credit (bool): Whether to allow for "partial" credit for
        answers (by default assigned a score of 0.5). Defaults
        to `False`. Note that this parameter is only used
        with the default `instructions` (as custom instructions
        provide their own prompts for grades).
      model (list[str | Model] | str | Model | None): Model or Models to use for grading. If     multiple models are passed, a majority vote of their grade will be returned. By default the model being evaluated is used.
    """
    # bind variables
    get_scorer = partial(
        _model_graded_qa_single,
        template,
        instructions,
        grade_pattern,
        include_history,
        partial_credit,
    )
    # if only a single model is passed, return a single scorer
    if model is None or not isinstance(model, list):
        return get_scorer(model)

    # otherwise, use multi scorer
    assert isinstance(model, list)
    scorers = [get_scorer(model) for model in model]
    return multi_scorer(scorers, "mode")


@scorer(metrics=[accuracy(), stderr()])
def _model_graded_qa_single(
    template: str | None = None,
    instructions: str | None = None,
    grade_pattern: str | None = None,
    include_history: bool | Callable[[TaskState], str] = False,
    partial_credit: bool = False,
    model: str | Model | None = None,
) -> Scorer:
    # returns a scorer that does model graded qa for a single model

    # resolve grading template, instructions, and grade_pattern
    template = template if template else DEFAULT_MODEL_GRADED_QA_TEMPLATE
    grading_template = resource(template)
    instructions = (
        instructions if instructions else default_instructions(partial_credit)
    )

    async def score(state: TaskState, target: Target) -> Score:
        # resolve model
        nonlocal model
        model = model if isinstance(model, Model) else get_model(model)

        # metadata without grading template variables
        metadata = omit(
            state.metadata, ["question", "answer", "criterion", "instructions"]
        )

        # present the question
        if include_history is True:
            question = chat_history(state)
        elif callable(include_history):
            question = include_history(state)
        else:
            question = state.input_text

        # format the scoring template
        score_prompt = grading_template.format(
            question=question,
            answer=state.output.completion,
            criterion=target.text,
            instructions=instructions,
            **metadata,
        )

        # query the model for the score
        result = await model.generate(score_prompt)

        # extract the grade
        match = re.search(grade_pattern or DEFAULT_GRADE_PATTERN, result.completion)
        if match:
            return Score(
                value=match.group(1),
                answer=state.output.completion,
                explanation=result.completion,
                metadata=dict(
                    grading=[
                        ChatMessageUser(content=score_prompt),
                        result.message,
                    ]
                ),
            )
        else:
            return Score(
                value=INCORRECT,
                explanation="Grade not found in model output: "
                + f"{result.completion}",
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


DEFAULT_GRADE_PATTERN = r"(?i)GRADE\s*:\s*([CPI])(.*)$"
"""Regex to extract the grade from the COT above."""


def chat_history(state: TaskState) -> str:
    # filter out system messages
    messages: list[ChatMessage] = [
        message
        for message in state.messages
        if not isinstance(message, ChatMessageSystem)
    ]

    # present message history (removing the final assistant message
    # and after as it will be contained in the 'Answer:'):
    messages = remove_last_match_and_after(
        messages, lambda message: isinstance(message, ChatMessageAssistant)
    )

    # begin history with text of first message (it will come right after
    # 'Task' or 'Question' in the template)
    history: list[str] = [messages[0].text]

    # for subsequent messages present with e.g. Assistant: {message.text}
    for message in messages[1:]:
        if isinstance(message, ChatMessageUser):
            history.append(f"User: {message.text}")
        elif isinstance(message, ChatMessageAssistant):
            assistant_message = [message.text] if message.text else []
            if message.tool_calls:
                assistant_message.extend(
                    [
                        format_function_call(tool_call.function, tool_call.arguments)
                        for tool_call in message.tool_calls
                    ]
                )
            history.append("Assistant: " + "\n\n".join(assistant_message))
        elif isinstance(message, ChatMessageTool):
            history.append(
                f"Tool ({message.function}): {message.tool_error or ''}{message.text}"
            )

    return "\n\n".join(history)
