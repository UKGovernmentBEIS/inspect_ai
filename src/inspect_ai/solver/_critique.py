from inspect_ai.model import (
    ChatMessageUser,
    Model,
    get_model,
)
from inspect_ai.util import resource

from ._solver import Generate, Solver, TaskState, solver


@solver
def self_critique(
    critique_template: str | None = None,
    completion_template: str | None = None,
    model: str | Model | None = None,
) -> Solver:
    """Solver which uses a model to critique the original answer.

    The `critique_template` is used to generate a critique
    and the `completion_template` is used to play that critique
    back to the model for an improved response. Note that you
    can specify an alternate `model` for critique (you don't
    need to use the model being evaluated).

    Args:
      critique_template (str | None): String or path to file
         containing critique template. The template uses two
         variables: `question` and `completion`.
      completion_template (str | None): String or path to file
          containing completion template. The template uses
          three variables: `question`,  `completion`, and `critique`
      model (str | Model | None): Alternate model to be used
         for critique (by default the model being evaluated
         is used).
    """
    # resolve templates
    critique_template = resource(critique_template or DEFAULT_CRITIQUE_TEMPLATE)
    completion_template = resource(
        completion_template or DEFAULT_CRITIQUE_COMPLETION_TEMPLATE
    )

    # resolve model
    model = get_model(model)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # run critique
        critique = await model.generate(
            critique_template.format(
                question=state.input_text,
                completion=state.output.completion,
            )
        )

        # add the critique as a user message
        state.messages.append(
            ChatMessageUser(
                content=completion_template.format(
                    question=state.input_text,
                    completion=state.output.completion,
                    critique=critique.completion,
                ),
            )
        )

        # regenerate
        return await generate(state)

    return solve


DEFAULT_CRITIQUE_TEMPLATE = r"""
Given the following question and answer, please critique the answer. A good answer comprehensively answers the question and NEVER refuses to answer. If the answer is already correct do not provide critique - simply respond 'The original answer is fully correct'.

[BEGIN DATA]
***
[Question]: {question}
***
[Answer]: {completion}
***
[END DATA]

Critique: """


DEFAULT_CRITIQUE_COMPLETION_TEMPLATE = r"""
Given the following question, initial answer and critique please generate an improved answer to the question:

[BEGIN DATA]
***
[Question]: {question}
***
[Answer]: {completion}
***
[Critique]: {critique}
***
[END DATA]

If the original answer is already correct, just repeat the original answer exactly. Provide your answer at the end on its own line in the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the question.
"""
