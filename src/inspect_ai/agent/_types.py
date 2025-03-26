from typing import Awaitable, Callable, NamedTuple, TypeAlias

from inspect_ai.agent._agent import AgentState
from inspect_ai.scorer._metric import Score, ValueToFloat, value_to_float

DEFAULT_HANDOFF_PROMPT = """
You are part of a multi-agent system designed to make agent coordination and
execution easy. Agents uses two primary abstraction: **Agents** and **Handoffs**.
An agent encompasses instructions and tools and can hand off a conversation to
another agent when appropriate. Handoffs are achieved by calling a handoff function,
generally named `transfer_to_<agent_name>`. Transfers between agents are handled
seamlessly in the background; do not mention or draw attention to these transfers
in your conversation with the user.
"""


DEFAULT_ASSISTANT_PROMPT = """
You are a helpful assistant attempting to submit the best possible answer.
You have several tools available to help with finding the answer. You will
see the result of tool calls right after sending the message. If you need
to perform multiple actions, you can always send more messages with additional
tool calls. Do some reasoning before your actions, describing what tool calls
you are going to use and how they fit into your plan.

When you have completed the task and have an answer, call the {submit}()
tool to report it.
"""


class AgentPrompt(NamedTuple):
    """Prompt for agent."""

    instructions: str | None = None
    """Agent-specific contextual instructions."""

    handoff_prompt: str | None = DEFAULT_HANDOFF_PROMPT
    """Prompt used when there are additional handoff agents active."""

    assistant_prompt: str | None = DEFAULT_ASSISTANT_PROMPT
    """Prompt for assistant (covers tool use, submit tool, CoT, etc.)."""


AgentContinue: TypeAlias = Callable[[AgentState], Awaitable[bool | str]]
"""Function called to determine whether the agent should continue.

Returns `True` to continue (with no additional messages inserted),
return `False` to stop. Returns `str` to continue with an additional
custom user message inserted.
"""


class AgentAttempts(NamedTuple):
    """Configure a react agent to make multiple attempts.

    Submissions are evaluated using the task's main scorer, with value of 1.0
    indicating a correct answer. Scorer values are converted to float (e.g.
    "C" becomes 1.0) using the standard value_to_float() function. Provide an
    alternate conversion scheme as required via `score_value`.
    """

    attempts: int = 1
    """Maximum number of attempts."""

    incorrect_message: str | Callable[[AgentState, list[Score]], Awaitable[str]] = (
        "Your submission was incorrect. Please proceed and attempt to find the correct answer."
    )
    """User message reply for an incorrect submission from the model. Alternatively,
    an async function which returns a message."""

    score_value: ValueToFloat = value_to_float()
    """Function used to extract float from scores (defaults to standard value_to_float())"""


class AgentSubmit(NamedTuple):
    """Configure the submit tool of a react agent."""

    name: str = "submit"
    """Name for submit tool."""

    description: str = "Submit an answer for evaluation."
    """Description of submit tool."""
