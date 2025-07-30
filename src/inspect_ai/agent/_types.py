from typing import Awaitable, Callable, NamedTuple, TypeAlias

from inspect_ai.agent._agent import AgentState
from inspect_ai.scorer._metric import Score, ValueToFloat, value_to_float
from inspect_ai.tool._tool import Tool

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
"""

DEFAULT_SUBMIT_PROMPT = """
When you have completed the task and have an answer, call the {submit}()
tool to report it.
"""


class AgentPrompt(NamedTuple):
    """Prompt for agent."""

    instructions: str | None = None
    """Agent-specific contextual instructions."""

    handoff_prompt: str | None = DEFAULT_HANDOFF_PROMPT
    """Prompt used when there are additional handoff agents active.
    Pass `None` for no additional handoff prompt."""

    assistant_prompt: str | None = DEFAULT_ASSISTANT_PROMPT
    """Prompt for assistant (covers tool use, CoT, etc.).
    Pass `None` for no additional assistant prompt."""

    submit_prompt: str | None = DEFAULT_SUBMIT_PROMPT
    """Prompt to tell the model about the submit tool.

    Pass `None` for no additional submit prompt.

    This prompt is not used if the `assistant_prompt` contains a
    {submit} placeholder.
    """


DEFAULT_CONTINUE_PROMPT = """
Please proceed to the next step using your best judgement. If you believe you
have completed the task, please call the `{submit}()` tool with your final answer.
"""

DEFAULT_CONTINUE_PROMPT_NO_SUBMIT = """
Please proceed to the next step using your best judgement.
"""


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

    name: str | None = None
    """Name for submit tool (defaults to 'submit')."""

    description: str | None = None
    """Description of submit tool (defaults to 'Submit an answer for evaluation')."""

    tool: Tool | None = None
    """Alternate implementation for submit tool.

    The tool can provide its `name` and `description` internally,
    or these values can be overriden by the `name` and `description`
    fields in `AgentSubmit`

    The tool should return the `answer` provided to it for scoring.
    """

    answer_only: bool = False
    """Set the completion to only the answer provided by the submit tool.

    By default, the answer is appended (with `answer_delimiter`) to whatever
    other content the model generated along with the call to `submit()`."""

    answer_delimiter: str = "\n\n"
    """Delimter used when appending submit tool answer to other content the model generated along with the call to `submit()`."""

    keep_in_messages: bool = False
    """Keep the submit tool call in the message history.

    Defaults to `False`, which results in calls to the `submit()` tool being
    removed from message history so that the model's response looks like a
    standard assistant message.

    This is particularly important for multi-agent systems where the presence
    of `submit()` calls in the history can cause coordinator agents to terminate
    early because they think they are done. You should therefore not set this to
    `True` if you are using `handoff()` in a multi-agent system.
    """
