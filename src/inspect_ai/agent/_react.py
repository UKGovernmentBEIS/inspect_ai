from logging import getLogger
from typing import Literal, Sequence

from inspect_ai._util._async import is_callable_coroutine
from inspect_ai._util.content import Content, ContentText
from inspect_ai.log._transcript import transcript
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._model import Model, get_model
from inspect_ai.model._model_output import ModelUsage
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
    DEFAULT_CONTINUE_PROMPT_NO_SUBMIT,
    AgentAttempts,
    AgentCompaction,
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
    submit: AgentSubmit | bool | None = None,
    on_continue: str | AgentContinue | None = None,
    truncation: Literal["auto", "disabled"] | MessageFilter = "disabled",
    compaction: AgentCompaction | None = None,
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
       submit: Use a submit tool for reporting the final answer. Defaults to `True`
          which uses the default submit behavior. Pass an `AgentSubmit` to
          customize the behavior or pass `False` to disable the submit tool.
       on_continue: Message to play back to the model to urge it to continue
          when it stops calling tools. Use the placeholder {submit} to refer to
          the submit tool within the message. Alternatively, an async function
          to call to determine whether the loop should continue and what message
          to play back. Note that this function is called on _every_ iteration of
          the loop so if you only want to send a message back when the model fails
          to call tools you need to code that behavior explicitly.
       truncation: Truncate the conversation history in the event of a context
          window overflow. Defaults to "disabled" which does no truncation. Pass
          "auto" to use `trim_messages()` to reduce the context size. Pass a
          `MessageFilter` function to do custom truncation.
       compaction: Configure proactive context compaction. When enabled, the agent
          monitors token usage and automatically summarizes conversation history
          when approaching the context limit. This is complementary to `truncation`:
          compaction is proactive (triggers before overflow), while truncation is
          reactive (handles overflow after it occurs). Pass an `AgentCompaction`
          to enable and configure compaction behavior.

    Returns:
        ReAct agent.
    """
    # if there is no submit tool then delegate to react_no_submit
    if submit is False:
        # if the user passes a `str` for on_continue this won't do anything
        if isinstance(on_continue, str):
            raise ValueError(
                "Passing a string to on_continue with no submit tool is not permitted, "
                + "because in this case the agent will always terminate when no tool "
                + "calls are made."
            )

        return react_no_submit(
            name=name,
            description=description,
            prompt=prompt,
            tools=tools,
            model=model,
            on_continue=on_continue,
            truncation=truncation,
            compaction=compaction,
        )

    # if submit is True or None then use default AgentSubmit
    if submit is True or submit is None:
        submit = AgentSubmit()

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
    submit_tool = (
        ToolDef(
            submit.tool or default_submit_tool(),
            name=submit.name,
            description=submit.description,
        )
        if not isinstance(submit.tool, ToolDef)
        else submit.tool
    )
    tools.append(submit_tool)

    # resolve prompt / system message
    system_message = _prompt_to_system_message(prompt, tools, submit_tool.name)

    # resolve attempts
    attempts = AgentAttempts(attempts) if isinstance(attempts, int) else attempts

    # validate compaction
    if compaction is not None:
        if not 0.0 < compaction.threshold < 1.0:
            raise ValueError("compaction.threshold must be between 0 and 1")
        if compaction.max_context_tokens <= 0:
            raise ValueError("compaction.max_context_tokens must be positive")

    def submission(tool_results: list[ChatMessage]) -> str | None:
        return next(
            (
                result.text
                for result in tool_results
                if isinstance(result, ChatMessageTool)
                and result.function == submit_tool.name
                # Require that the submit tool call has no error
                and result.error is None
            ),
            None,
        )

    async def execute(state: AgentState) -> AgentState:
        async with mcp_connection(tools):
            # prepend system message if we have one
            if system_message:
                state.messages.insert(0, system_message)

            # resolve overflow handling
            overflow = _resolve_overflow(truncation)

            # track attempts
            attempt_count = 0

            # track compaction state (initial messages + active window)
            initial_messages_count = len(state.messages)
            compaction_start_index = initial_messages_count
            compaction_count = 0

            # main loop = will terminate after submit (subject to max_attempts)
            # or if a message or token limit is hit
            while True:
                # get active messages for generation (when compaction is enabled)
                active_messages = (
                    _get_active_messages(
                        state.messages, compaction_start_index, initial_messages_count
                    )
                    if compaction is not None
                    else None
                )

                # generate output and append assistant message
                state = await _agent_generate(model, state, tools, active_messages)

                # check for context window overflow
                if state.output.stop_reason == "model_length":
                    state, handled = await _handle_overflow(state, overflow)
                    if handled:
                        continue
                    else:
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

                        # also populate the message text (as the submit tool will be removed)
                        if (
                            not submit.keep_in_messages
                            and len(state.output.choices) > 0
                        ):
                            message = state.output.choices[0].message
                            if isinstance(message.content, str):
                                message.content = f"{message.content}{submit.answer_delimiter}{answer}".strip()
                            else:
                                message.content.append(ContentText(text=answer))

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

                # check compaction threshold (proactive, before overflow)
                if compaction is not None and state.output.usage:
                    total_input_tokens = _get_total_input_tokens(
                        state.output.model, state.output.usage
                    )
                    threshold_tokens = int(
                        compaction.max_context_tokens * compaction.threshold
                    )
                    if total_input_tokens > threshold_tokens:
                        # check if we can still compact
                        can_compact = (
                            compaction.max_compactions is None
                            or compaction_count < compaction.max_compactions
                        )
                        if can_compact:
                            compaction_start_index = await _perform_compaction(
                                state=state,
                                compaction_start_index=compaction_start_index,
                                initial_messages_count=initial_messages_count,
                                model=model,
                                compaction_prompt=compaction.prompt,
                            )
                            compaction_count += 1

                # call the on_continue hook (if any)
                if callable(on_continue):
                    do_continue = await _call_on_continue(on_continue, state)
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
                        # send back the user message
                        state.messages.append(
                            ChatMessageUser(
                                content=do_continue.format(submit=submit_tool.name)
                            )
                        )
                    elif isinstance(do_continue, AgentState):
                        state.messages = do_continue.messages
                        state.output = do_continue.output
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

            if not submit.keep_in_messages:
                # once we are complete, remove submit tool calls from the history
                # (as they will potentially confuse parent agents who also have
                # their own submit tools that they are 'watching' for)
                state.messages = _remove_submit_tool(state.messages, submit_tool.name)
            return state

    return _resolve_agent(execute, name, description)


def react_no_submit(
    *,
    name: str | None,
    description: str | None,
    prompt: str | AgentPrompt | None,
    tools: Sequence[Tool | ToolDef | ToolSource] | None,
    model: str | Model | Agent | None,
    on_continue: AgentContinue | None,
    truncation: Literal["auto", "disabled"] | MessageFilter,
    compaction: AgentCompaction | None,
) -> Agent:
    # resolve tools
    tools = list(tools) if tools is not None else []

    # resolve prompt / system message
    system_message = _prompt_to_system_message(prompt, tools, None)

    # validate compaction
    if compaction is not None:
        if not 0.0 < compaction.threshold < 1.0:
            raise ValueError("compaction.threshold must be between 0 and 1")
        if compaction.max_context_tokens <= 0:
            raise ValueError("compaction.max_context_tokens must be positive")

    async def execute(state: AgentState) -> AgentState:
        async with mcp_connection(tools):
            # prepend system message if we have one
            if system_message:
                state.messages.insert(0, system_message)

            # resolve overflow handling
            overflow = _resolve_overflow(truncation)

            # track compaction state (initial messages + active window)
            initial_messages_count = len(state.messages)
            compaction_start_index = initial_messages_count
            compaction_count = 0

            # main loop
            while True:
                # get active messages for generation (when compaction is enabled)
                active_messages = (
                    _get_active_messages(
                        state.messages, compaction_start_index, initial_messages_count
                    )
                    if compaction is not None
                    else None
                )

                # generate output and append assistant message
                state = await _agent_generate(model, state, tools, active_messages)

                # check for context window overflow
                if state.output.stop_reason == "model_length":
                    state, handled = await _handle_overflow(state, overflow)
                    if handled:
                        continue
                    else:
                        break

                # resolve tool calls (if any)
                if state.output.message.tool_calls:
                    # call tool functions
                    messages, output = await execute_tools(state.messages, tools)
                    state.messages.extend(messages)
                    if output:
                        state.output = output

                # check compaction threshold (proactive, before overflow)
                if compaction is not None and state.output.usage:
                    total_input_tokens = _get_total_input_tokens(
                        state.output.model, state.output.usage
                    )
                    threshold_tokens = int(
                        compaction.max_context_tokens * compaction.threshold
                    )
                    if total_input_tokens > threshold_tokens:
                        # check if we can still compact
                        can_compact = (
                            compaction.max_compactions is None
                            or compaction_count < compaction.max_compactions
                        )
                        if can_compact:
                            compaction_start_index = await _perform_compaction(
                                state=state,
                                compaction_start_index=compaction_start_index,
                                initial_messages_count=initial_messages_count,
                                model=model,
                                compaction_prompt=compaction.prompt,
                            )
                            compaction_count += 1

                # call the on_continue hook (if any)
                if on_continue:
                    do_continue = await _call_on_continue(on_continue, state)
                    if do_continue is True:
                        if not state.output.message.tool_calls:
                            state.messages.append(
                                ChatMessageUser(
                                    content=DEFAULT_CONTINUE_PROMPT_NO_SUBMIT
                                )
                            )
                    elif isinstance(do_continue, str):
                        state.messages.append(ChatMessageUser(content=do_continue))
                    elif isinstance(do_continue, AgentState):
                        state.messages = do_continue.messages
                        state.output = do_continue.output
                    else:
                        break
                elif not state.output.message.tool_calls:
                    break

            return state

    return _resolve_agent(execute, name, description)


def _prompt_to_system_message(
    prompt: str | AgentPrompt | None,
    tools: list[Tool | ToolDef | ToolSource],
    submit_tool: str | None,
) -> ChatMessage | None:
    prompt = AgentPrompt(prompt) if isinstance(prompt, str) else prompt
    if prompt:
        prompt_lines: list[str] = []
        if prompt.instructions:
            prompt_lines.append(prompt.instructions)
        if prompt.handoff_prompt and has_handoff(tools):
            prompt_lines.append(prompt.handoff_prompt)
        if prompt.assistant_prompt:
            if (
                submit_tool
                and ("{submit}" not in prompt.assistant_prompt)
                and prompt.submit_prompt
            ):
                assistant_prompt = f"{prompt.assistant_prompt}\n{prompt.submit_prompt.format(submit=submit_tool)}"
            else:
                assistant_prompt = prompt.assistant_prompt.format(
                    submit=submit_tool or "submit"
                )
            prompt_lines.append(assistant_prompt)
        prompt_content = "\n\n".join(prompt_lines)
        system_message: ChatMessage | None = ChatMessageSystem(content=prompt_content)
    else:
        system_message = None
    return system_message


def _resolve_overflow(
    truncation: Literal["auto", "disabled"] | MessageFilter,
) -> MessageFilter | None:
    # resolve overflow handling
    if truncation == "auto":
        overflow: MessageFilter | None = trim_messages
    elif truncation == "disabled":
        overflow = None
    else:
        overflow = truncation
    return overflow


def _get_total_input_tokens(model_name: str, usage: ModelUsage) -> int:
    """Get total input tokens accounting for provider differences.

    Anthropic reports cached tokens separately from input_tokens.
    OpenAI includes cached tokens in input_tokens already.

    Args:
        model_name: Name of the model used for generation.
        usage: ModelUsage object from the model output.

    Returns:
        Total input tokens including any cached tokens.
    """
    total = usage.input_tokens

    # Anthropic models need cached tokens added separately
    if "claude" in model_name.lower():
        total += usage.input_tokens_cache_read or 0
        total += usage.input_tokens_cache_write or 0

    return total


def _get_active_messages(
    messages: list[ChatMessage],
    compaction_start_index: int,
    initial_messages_count: int,
) -> list[ChatMessage]:
    """Get messages to send to model (active window only).

    Returns a list containing:
    - All initial messages (messages[0:initial_messages_count])
    - All messages from compaction_start_index onwards

    Args:
        messages: Full message history.
        compaction_start_index: Index where active window starts.
        initial_messages_count: Number of initial messages to always include.

    Returns:
        List of messages to send to the model.
    """
    result: list[ChatMessage] = []

    # Always include all initial messages
    result.extend(messages[0:initial_messages_count])

    # Include messages from compaction start point (if after initial messages)
    if compaction_start_index >= initial_messages_count:
        result.extend(messages[compaction_start_index:])

    return result


async def _perform_compaction(
    state: AgentState,
    compaction_start_index: int,
    initial_messages_count: int,
    model: str | Model | Agent | None,
    compaction_prompt: str,
) -> int:
    """Perform context compaction by summarizing conversation history.

    Sends the full conversation to the model with an instruction to summarize,
    enabling cache hits on the conversation prefix.

    Args:
        state: Current agent state with full message history.
        compaction_start_index: Current index where active window starts.
        initial_messages_count: Number of initial messages to preserve.
        model: Model to use for summarization. If an Agent is passed, the
            default model is used instead since compaction is a simple
            summarization task.
        compaction_prompt: Instruction prompt for generating the summary.

    Returns:
        New compaction_start_index (index of the summary message).
    """
    # Log compaction start
    transcript().info(
        f"Context compaction started: {len(state.messages)} messages, "
        f"active window from index {compaction_start_index}"
    )

    # Send full conversation with instruction at the end (cache-friendly)
    messages_for_summary = list(state.messages)
    instruction = ChatMessageUser(content=compaction_prompt)

    # For compaction, we use the model directly (not an Agent)
    # If model is an Agent, use None to get the default model
    model_for_summary = model if isinstance(model, str | Model) or model is None else None
    resolved_model = get_model(model_for_summary)
    summary_output = await resolved_model.generate(
        messages_for_summary + [instruction],
        tools=[],
    )

    # Create summary message and append to full history
    summary_message = ChatMessageUser(
        content=f"[CONTEXT COMPACTION SUMMARY]\n\n{summary_output.completion}"
    )
    state.messages.append(summary_message)

    # New compaction start is the index of the summary message
    new_compaction_start = len(state.messages) - 1

    # Log compaction complete
    summary_tokens = (
        summary_output.usage.output_tokens if summary_output.usage else 0
    )
    transcript().info(
        f"Context compaction completed: summarized {len(messages_for_summary)} messages, "
        f"new active window from index {new_compaction_start}, "
        f"summary tokens: {summary_tokens}"
    )

    return new_compaction_start


async def _handle_overflow(
    state: AgentState, overflow: MessageFilter | None
) -> tuple[AgentState, bool]:
    from inspect_ai.log._transcript import transcript

    if overflow is not None:
        previous_messages = state.messages[:-1]
        state.messages = await overflow(previous_messages)
        if len(state.messages) < len(previous_messages):
            transcript().info(
                "Agent exceeded model context window, truncating messages and continuing."
            )
            return state, True

    # no overflow policy or overflow didn't reduce conversation length
    transcript().info("Agent terminated: model context window exceeded")
    return state, False


async def _agent_generate(
    model: str | Model | Agent | None,
    state: AgentState,
    tools: Sequence[Tool | ToolDef | ToolSource],
    active_messages: list[ChatMessage] | None = None,
) -> AgentState:
    """Generate model output and append assistant message.

    Args:
        model: Model or agent to use for generation.
        state: Current agent state with full message history.
        tools: Tools available for the agent.
        active_messages: When provided, use these messages for generation instead
            of state.messages. The assistant message is still appended to
            state.messages. This is used for compaction where we want to send
            only a subset of messages to the model while preserving full history.

    Returns:
        Updated agent state with new output and message appended.
    """
    # use active_messages if provided, otherwise use state.messages
    messages_for_generation = active_messages if active_messages is not None else None

    # convert model to agent
    if isinstance(model, str | Model) or model is None:
        # direct model generation with optional active_messages
        resolved_model = get_model(model)
        messages = (
            messages_for_generation
            if messages_for_generation is not None
            else state.messages
        )
        state.output = await resolved_model.generate(messages, tools)
        state.messages.append(state.output.message)
        return state

    # model is an Agent - resolve tools and call it
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

    # when using an Agent as model with active_messages, we need to create
    # a temporary state with active_messages and then merge results back
    if messages_for_generation is not None:
        temp_state = AgentState(messages=list(messages_for_generation))
        temp_state = await model(temp_state, resolved_tools)
        # append new messages from the sub-agent to full state
        for msg in temp_state.messages[len(messages_for_generation) :]:
            state.messages.append(msg)
        state.output = temp_state.output
        return state

    # call the agent with full state
    return await model(state, resolved_tools)


async def _call_on_continue(
    on_continue: AgentContinue, state: AgentState
) -> str | bool | AgentState:
    if not is_callable_coroutine(on_continue):
        raise ValueError("The on_continue function must be async.")
    return await on_continue(state)


def _resolve_agent(agent: Agent, name: str | None, description: str | None) -> Agent:
    if name is not None or description is not None:
        return agent_with(agent, name=name, description=description)
    else:
        return agent


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
            new_tools_calls = [
                tool_call
                for tool_call in message.tool_calls
                if tool_call.function != submit_name
            ]

            # If a submit tool call was removed, we need to update the message
            if len(new_tools_calls) < len(message.tool_calls):
                # Some models (OpenAI) don't like to see the reasoning
                # content item that led to the submit tool call, so we
                # remove the last reasoning item
                new_content: str | list[Content] = message.content
                if isinstance(new_content, list):
                    new_content = new_content.copy()
                    indices = [
                        i for i, x in enumerate(new_content) if x.type == "reasoning"
                    ]
                    if indices:
                        new_content.pop(indices[-1])

                # update w/ new tool calls and new content
                message = message.model_copy(
                    update=dict(
                        tool_calls=new_tools_calls,
                        content=new_content,
                    ),
                )

        # always append message
        filtered.append(message)

    return filtered
