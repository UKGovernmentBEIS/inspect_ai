from typing import Any

from inspect_ai.model import ChatMessageSystem
from inspect_ai.util import resource

from ._solver import Generate, Solver, solver
from ._task_state import TaskState
from ._util import append_system_message


@solver
def prompt_template(template: str, **params: dict[str, Any]) -> Solver:
    """Parameterized prompt template.

    Prompt template containing a `{prompt}` placeholder and any
    number of additional `params`.

    Args:
      template (str | list[Message]):
          The conversation template to use. A simple string or
          a list of messages
      **params (dict[str,Any]):
          A mapping of the parameters to fill into the template
          excluding the `{prompt}` parameter which is taken
          from the input.

    Returns:
      A solver that uses the specified prompt template.
    """
    # determine the prompt template
    prompt_template = resource(template)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        prompt = state.user_prompt
        prompt.text = prompt_template.format(prompt=prompt.text, **params)
        return state

    return solve


@solver
def system_message(message: str) -> Solver:
    """Solver which inserts a system message into the conversation.

    The new message will go after other system messages (if there
    are none it will be inserted at the beginning of the conversation).

    Args:
       message (str): System message.
    """
    # read template
    content = resource(message)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        append_system_message(state.messages, ChatMessageSystem(content=content))
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
       template (str): String or path to file containing CoT template.
          The template uses a single variable: `prompt`.
    """
    return prompt_template(template)
