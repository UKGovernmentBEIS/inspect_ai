from typing import Any

from inspect_ai._util.dict import omit
from inspect_ai._util.format import format_template
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.util import resource

from ._solver import Generate, Solver, solver
from ._task_state import TaskState
from ._util import append_system_message


@solver
def prompt_template(template: str, **params: Any) -> Solver:
    """Parameterized prompt template.

    Prompt template containing a `{prompt}` placeholder and any
    number of additional `params`. All values contained in sample
    `metadata` and `store` are also automatically included in the
    `params`.

    Args:
      template: Template for prompt.
      **params: Parameters to fill into the template.

    Returns:
      A solver that uses the specified prompt template.
    """
    # determine the prompt template
    prompt_template = resource(template)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        prompt = state.user_prompt
        kwargs = omit(state.metadata | state.store._data, ["prompt"]) | params
        prompt.text = format_template(prompt_template, {"prompt": prompt.text} | kwargs)
        return state

    return solve


@solver
def system_message(template: str, **params: Any) -> Solver:
    """Solver which inserts a system message into the conversation.

    System message template containing any number of optional `params`.
    for substitution using the `str.format()` method. All values
    contained in sample `metadata` and `store` are also automatically
    included in the `params`.

    The new message will go after other system messages (if there
    are none it will be inserted at the beginning of the conversation).

    Args:
      template: Template for system message.
      **params: Parameters to fill into the template.

    Returns:
      A solver that inserts the parameterised system message.
    """
    # read template
    content = resource(template)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        kwargs = state.metadata | state.store._data | params
        append_system_message(
            state.messages, ChatMessageSystem(content=format_template(content, kwargs))
        )
        return state

    return solve


@solver
def user_message(template: str, **params: Any) -> Solver:
    """Solver which inserts a user message into the conversation.

    User message template containing any number of optional `params`.
    for substitution using the `str.format()` method. All values
    contained in sample `metadata` and `store` are also automatically
    included in the `params`.

    Args:
      template: Template for user message.
      **params: Parameters to fill into the template.

    Returns:
      A solver that inserts the parameterised user message.
    """
    # read template
    content = resource(template)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        kwargs = state.metadata | state.store._data | params
        state.messages.append(ChatMessageUser(content=format_template(content, kwargs)))
        return state

    return solve


@solver
def assistant_message(template: str, **params: Any) -> Solver:
    """Solver which inserts an assistant message into the conversation.

    Assistant message template containing any number of optional `params`.
    for substitution using the `str.format()` method. All values
    contained in sample `metadata` and `store` are also automatically
    included in the `params`.

    Args:
      template: Template for assistant message.
      **params: Parameters to fill into the template.

    Returns:
      A solver that inserts the parameterised assistant message.
    """
    # read template
    content = resource(template)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        kwargs = state.metadata | state.store._data | params
        state.messages.append(
            ChatMessageAssistant(
                content=format_template(content, kwargs), model=state.model.name
            )
        )
        return state

    return solve


DEFAULT_COT_TEMPLATE = r"""
{prompt}

Before answering, reason in a step-by-step manner as to get the right answer. Provide your answer at the end on its own line in the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the question.
"""


@solver
def chain_of_thought(template: str = DEFAULT_COT_TEMPLATE) -> Solver:
    """Solver which modifies the user prompt to encourage chain of thought.

    Args:
       template: String or path to file containing CoT template.
          The template uses a single variable: `prompt`.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.user_prompt.text = template.format(prompt=state.user_prompt.text)
        return state

    return solve
