from logging import getLogger
from typing import Awaitable, Callable, NamedTuple, TypeAlias

from inspect_ai._util._async import is_callable_coroutine
from inspect_ai.agent._handoff import has_handoff
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._model import Model, get_model
from inspect_ai.scorer._metric import Score, ValueToFloat, value_to_float
from inspect_ai.scorer._score import score
from inspect_ai.tool._tool import Tool, ToolResult, tool
from inspect_ai.tool._tool_with import tool_with

from ._agent import Agent, AgentState, agent

logger = getLogger(__name__)

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


class ReactAttempts(NamedTuple):
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


class ReactSubmit(NamedTuple):
    """Configure the submit tool of a react agent."""

    name: str = "submit"
    """Name for submit tool."""

    description: str = "Submit an answer for evaluation."
    """Description of submit tool."""


ReactContinue: TypeAlias = Callable[[AgentState], Awaitable[bool | str]]
"""Function called to determine whether the agent should continue.

Returns `True` to continue (with no additional messages inserted),
return `False` to stop. Returns `str` to continue with an additional
custom user message inserted.
"""


class ReactPrompt(NamedTuple):
    """Prompt for agent."""

    instructions: str | None = None
    """Agent-specific contextual instructions."""

    handoff_prompt: str | None = DEFAULT_HANDOFF_PROMPT
    """Prompt used when there are additional handoff agents active."""

    assistant_prompt: str | None = DEFAULT_ASSISTANT_PROMPT
    """Prompt for assistant (covers tool use, submit tool, CoT, etc.)."""


@agent
def react(
    *,
    prompt: str | ReactPrompt | None = ReactPrompt(),
    tools: list[Tool] | None = None,
    model: str | Model | None = None,
    attempts: int | ReactAttempts = 1,
    submit: ReactSubmit = ReactSubmit(),
    on_continue: ReactContinue | None = None,
) -> Agent:
    """ReAct agent.

    Extensible ReAct agent based on the paper [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629).

    The agent runs a tool use loop until the model submits an answer using the
    `submit()` tool. Use `instructions` to tailor the agent's system message
    (the default `instructions` provides a basic ReAct prompt).

    Use the `attempts` option to enable additional submissions if the initial
    submission(s) are incorrect (by default, no additional attempts are permitted).

    By default, the model will be urged to continue if it fails to call
    a tool. Customise this behavior using the `on_continue` option.

    Args:
       prompt: Prompt for agent. Includes agent-specific contextual `instructions`
          as well as an optional `assistant_prompt` and `handoff_prompt` (for agents
          that use handoffs). both are provided by default but can be removed or
          customized). Pass `str` to specify the instructions and use the defaults
          for handoff and prompt messages.
       tools: Tools available for the agent.
       model: Model to use for agent (defaults to currently evaluated model)
       attempts: Configure agent to make multiple attempts.
       submit: Configure submit tool used by agent.
       on_continue: Optional async function to call to determine whether the loop
          should continue (executed on every turn). By default, urges the model
          to continue when it doesn't make a tool call.

    Returns:
        ReAct agent.
    """
    # resolve prompt / system message
    prompt = ReactPrompt(prompt) if isinstance(prompt, str) else prompt
    if prompt:
        prompt_lines: list[str] = []
        if prompt.instructions:
            prompt_lines.append(prompt.instructions)
        if prompt.handoff_prompt and has_handoff(tools):
            prompt_lines.append(prompt.handoff_prompt)
        if prompt.assistant_prompt:
            prompt_lines.append(prompt.assistant_prompt)
        system_message: ChatMessage | None = ChatMessageSystem(
            content="\n\n".join(prompt_lines)
        )
    else:
        system_message = None

    # resolve on_continue
    if on_continue is None:
        # by default, always continue (inserting an encouragement message
        # if the model failed to call a tool)
        async def no_tools_continue(state: AgentState) -> bool | str:
            if not state.output.message.tool_calls:
                return "Please proceed to the next step using your best judgement."
            else:
                return True

        on_continue = no_tools_continue

    # validate that on_continue is async
    if not is_callable_coroutine(on_continue):
        raise ValueError("The on_continue function must be async.")

    # resolve attempts
    attempts = ReactAttempts(attempts) if isinstance(attempts, int) else attempts

    # submission tool
    @tool
    def submit_tool() -> Tool:
        async def execute(answer: str) -> ToolResult:
            """Submit an answer for evaluation.

            Args:
              answer (str): Submitted answer
            """
            return answer

        return execute

    # helper to extract a submitted answer
    def submission(tool_results: list[ChatMessage]) -> str | None:
        return next(
            (
                result.text
                for result in tool_results
                if isinstance(result, ChatMessageTool)
                and result.function == submit.name
            ),
            None,
        )

    # resolve tools
    tools = tools or []
    tools.append(tool_with(submit_tool(), submit.name, submit.description))

    async def execute(state: AgentState) -> AgentState:
        # append system message if we have one
        if system_message:
            state.messages.append(system_message)

        # track attempts
        attempt_count = 0

        # main loop = will terminate after submit (subject to max_attempts)
        # or if a message or token limit is hit
        while True:
            # generate output and append assistant message
            state.output = await get_model(model).generate(
                input=state.messages, tools=tools
            )
            state.messages.append(state.output.message)

            # check for context window overflow
            if state.output.stop_reason == "model_length":
                from inspect_ai.log._transcript import transcript

                transcript().info("Agent terminated: model context window exceeded")
                break

            # resolve tools calls (if any)
            if state.output.message.tool_calls:
                # call tool functions
                messages, output = await execute_tools(state.messages, tools)
                state.messages.extend(messages)
                if output:
                    state.output = output

                # was an answer submitted?
                answer = submission(messages)
                if answer:
                    # set the output to the answer for scoring
                    state.output.completion = answer

                    # exit if we are at max_attempts
                    attempt_count += 1
                    if attempt_count >= attempts.attempts:
                        break

                    # exit if the submission is successful
                    answer_scores = await score(state)
                    if attempts.score_value(answer_scores[0].value) == 1.0:
                        break

                    # otherwise notify the model that it was incorrect and continue
                    else:
                        if callable(attempts.incorrect_message):
                            if not is_callable_coroutine(attempts.incorrect_message):
                                raise ValueError(
                                    "The incorrect_message function must be async."
                                )
                            response_message: str = await attempts.incorrect_message(
                                state, answer_scores
                            )
                        else:
                            response_message = attempts.incorrect_message

                        state.messages.append(ChatMessageUser(content=response_message))

            # check if we should continue....
            do_continue = await on_continue(state)
            if isinstance(do_continue, str):
                state.messages.append(ChatMessageUser(content=do_continue))
            elif do_continue is False:
                break

        return state

    return execute
