from logging import getLogger
from typing import Literal, Sequence, cast

from inspect_ai._util._async import is_callable_coroutine
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._model import Model, get_model
from inspect_ai.model._trim import trim_messages
from inspect_ai.scorer._score import score
from inspect_ai.tool._mcp.connection import mcp_connection
from inspect_ai.tool._tool import Tool, ToolResult, ToolSource, tool
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_info import parse_tool_info

from ._agent import Agent, AgentState, agent, agent_with
from ._filter import MessageFilter
from ._handoff import has_handoff
from ._types import (
    DEFAULT_CONTINUE_PROMPT,
    AgentAttempts,
    AgentContinue,
    AgentPrompt,
    AgentSubmit,
)

logger = getLogger(__name__)


@agent
def react(
    *,
    name: str | None = None,
    description: str | None = None,
    prompt: str | AgentPrompt | None = AgentPrompt(),
    tools: Sequence[Tool | ToolDef | ToolSource] | None = None,
    model: str | Model | Agent | None = None,
    attempts: int | AgentAttempts = 1,
    submit: AgentSubmit = AgentSubmit(),
    on_continue: str | AgentContinue | None = None,
    truncation: Literal["auto", "disabled"] | MessageFilter = "disabled",
) -> Agent:
    """Extensible ReAct agent based on the paper [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629).

    Provide a `name` and `description` for the agent if you plan on using it
    in a multi-agent system (this is so other agents can clearly identify
    its name and purpose). These fields are not required when using `react()`
    as a top-level solver.

    The agent runs a tool use loop until the model submits an answer using the
    `submit()` tool. Use `instructions` to tailor the agent's system message
    (the default `instructions` provides a basic ReAct prompt).

    Use the `attempts` option to enable additional submissions if the initial
    submission(s) are incorrect (by default, no additional attempts are permitted).

    By default, the model will be urged to continue if it fails to call
    a tool. Customise this behavior using the `on_continue` option.

    Args:
       name: Agent name (required when using with `handoff()` or `as_tool()`)
       description: Agent description (required when using with `handoff()` or `as_tool()`)
       prompt: Prompt for agent. Includes agent-specific contextual `instructions`
          as well as an optional `assistant_prompt` and `handoff_prompt` (for agents
          that use handoffs). both are provided by default but can be removed or
          customized). Pass `str` to specify the instructions and use the defaults
          for handoff and prompt messages.
       tools: Tools available for the agent.
       model: Model to use for agent (defaults to currently evaluated model).
       attempts: Configure agent to make multiple attempts.
       submit: Configure submit tool used by agent.
       on_continue: Message to play back to the model to urge it to continue.
          Use the placeholder {submit} to refer to the submit tool within the message.
          Alternatively, an async function to call to determine whether the loop
          should continue and what message to play back. Note that this function
          is called on _every_ iteration of the loop so if you only want to send
          a message back when the model fails to call tools you need to code
          that behavior explicitly.
       truncation: Truncate the conversation history in the event of a context
          window overflow. Defaults to "disabled" which does no truncation. Pass
          "auto" to use `trim_messages()` to reduce the context size. Pass a
          `MessageFilter` function to do custom truncation.

    Returns:
        ReAct agent.
    """

    # default submit tool
    @tool(name="submit")
    def default_submit_tool() -> Tool:
        async def execute(answer: str) -> ToolResult:
            """Submit an answer for evaluation.

            Args:
              answer (str): Submitted answer
            """
            return answer

        return execute

    # resolve tools
    tools = list(tools) if tools is not None else []

    # resolve submit tool
    submit_tool = ToolDef(
        submit.tool or default_submit_tool(),
        name=submit.name,
        description=submit.description,
    )
    tools.append(submit_tool)

    # resolve prompt / system message
    prompt = AgentPrompt(prompt) if isinstance(prompt, str) else prompt
    if prompt:
        prompt_lines: list[str] = []
        if prompt.instructions:
            prompt_lines.append(prompt.instructions)
        if prompt.handoff_prompt and has_handoff(tools):
            prompt_lines.append(prompt.handoff_prompt)
        if prompt.assistant_prompt:
            prompt_lines.append(prompt.assistant_prompt)
        prompt_content = "\n\n".join(prompt_lines).format(submit=submit_tool.name)
        system_message: ChatMessage | None = ChatMessageSystem(content=prompt_content)
    else:
        system_message = None

    # resolve attempts
    attempts = AgentAttempts(attempts) if isinstance(attempts, int) else attempts

    def submission(tool_results: list[ChatMessage]) -> str | None:
        return next(
            (
                result.text
                for result in tool_results
                if isinstance(result, ChatMessageTool)
                and result.function == submit_tool.name
            ),
            None,
        )

    async def execute(state: AgentState) -> AgentState:
        async with mcp_connection(tools):
            # prepend system message if we have one
            if system_message:
                state.messages.insert(0, system_message)

            # resolve overflow handling
            if truncation == "auto":
                overflow = cast(MessageFilter | None, trim_messages)
            elif truncation == "disabled":
                overflow = None
            else:
                overflow = truncation

            # track attempts
            attempt_count = 0

            # main loop = will terminate after submit (subject to max_attempts)
            # or if a message or token limit is hit
            while True:
                # generate output and append assistant message
                state = await _agent_generate(model, state, tools)

                # check for context window overflow
                if state.output.stop_reason == "model_length":
                    from inspect_ai.log._transcript import transcript

                    if overflow is not None:
                        previous_messages = state.messages[:-1]
                        state.messages = await overflow(previous_messages)
                        if len(state.messages) < len(previous_messages):
                            transcript().info(
                                "Agent exceeded model context window, truncating messages and continuing."
                            )
                            continue

                    # no overflow policy or overflow didn't reduce conversation length
                    transcript().info("Agent terminated: model context window exceeded")
                    break

                # resolve tool calls (if any)
                if state.output.message.tool_calls:
                    # call tool functions
                    messages, output = await execute_tools(state.messages, tools)
                    state.messages.extend(messages)
                    if output:
                        state.output = output

                    # check for a submission
                    answer = submission(messages)
                    if answer is not None:
                        # set the output to the answer for scoring
                        if submit.answer_only:
                            state.output.completion = answer
                        else:
                            state.output.completion = f"{state.output.completion}{submit.answer_delimiter}{answer}".strip()

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
                                if not is_callable_coroutine(
                                    attempts.incorrect_message
                                ):
                                    raise ValueError(
                                        "The incorrect_message function must be async."
                                    )
                                response_message: str = (
                                    await attempts.incorrect_message(
                                        state, answer_scores
                                    )
                                )
                            else:
                                response_message = attempts.incorrect_message

                            state.messages.append(
                                ChatMessageUser(content=response_message)
                            )

                # call the on_continue hook (if any)
                if callable(on_continue):
                    if not is_callable_coroutine(on_continue):
                        raise ValueError("The on_continue function must be async.")
                    do_continue = await cast(AgentContinue, on_continue)(state)
                    if do_continue is True:
                        # if there were no tool calls we need to send back a user message
                        if not state.output.message.tool_calls:
                            state.messages.append(
                                ChatMessageUser(
                                    content=DEFAULT_CONTINUE_PROMPT.format(
                                        submit=submit_tool.name
                                    )
                                )
                            )
                    elif isinstance(do_continue, str):
                        state.messages.append(
                            ChatMessageUser(
                                content=do_continue.format(submit=submit_tool.name)
                            )
                        )
                    else:  # do_continue is False
                        break

                # if there is no on_continue hook then add a user message if there were no tool calls
                elif not state.output.message.tool_calls:
                    continue_msg = (
                        DEFAULT_CONTINUE_PROMPT
                        if on_continue is None
                        else str(on_continue)
                    )
                    state.messages.append(
                        ChatMessageUser(
                            content=continue_msg.format(submit=submit_tool.name)
                        )
                    )

            # once we are complete, remove submit tool calls from the history
            # (as they will potentially confuse parent agents who also have
            # their own submit tools that they are 'watching' for)
            state.messages = _remove_submit_tool(state.messages, submit_tool.name)
            return state

    if name is not None or description is not None:
        return agent_with(execute, name=name, description=description)
    else:
        return execute


async def _agent_generate(
    model: str | Model | Agent | None,
    state: AgentState,
    tools: Sequence[Tool | ToolDef | ToolSource],
) -> AgentState:
    # convert model to agent
    if isinstance(model, str | Model) or model is None:
        model = _model_generate(model)

    # resolve tools
    resolved_tools: list[Tool] = []
    for t in tools:
        if isinstance(t, ToolSource):
            resolved_tools.extend(await t.tools())
        elif isinstance(t, ToolDef):
            resolved_tools.append(t.as_tool())
        else:
            resolved_tools.append(t)

    # confirm we have a tools param
    agent_tool_info = parse_tool_info(model)
    if "tools" not in agent_tool_info.parameters.properties:
        raise ValueError(
            "Agent passed as model for react agent must have a tools parameter."
        )

    # call the agent
    return await model(state, resolved_tools)


def _model_generate(model: str | Model | None) -> Agent:
    async def generate(state: AgentState, tools: list[Tool]) -> AgentState:
        state.output = await get_model(model).generate(state.messages, tools)
        state.messages.append(state.output.message)
        return state

    return generate


def _remove_submit_tool(
    messages: list[ChatMessage], submit_name: str
) -> list[ChatMessage]:
    filtered: list[ChatMessage] = []
    for message in messages:
        # skip submit tool messages
        if isinstance(message, ChatMessageTool) and message.function == submit_name:
            continue

        # remove submit tool from assistant messages
        if isinstance(message, ChatMessageAssistant) and message.tool_calls:
            tools_calls = [
                tool_call
                for tool_call in message.tool_calls
                if tool_call.function != submit_name
            ]
            message = message.model_copy(update=dict(tool_calls=tools_calls))

        # always append message
        filtered.append(message)

    return filtered
