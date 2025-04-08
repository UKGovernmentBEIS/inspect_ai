from logging import getLogger

from inspect_ai._util._async import is_callable_coroutine
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.model._model import Model, get_model
from inspect_ai.scorer._score import score
from inspect_ai.tool._tool import Tool, ToolResult, tool
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_info import parse_tool_info
from inspect_ai.tool._tool_with import tool_with

from ._agent import Agent, AgentState, agent, agent_with
from ._handoff import has_handoff
from ._types import (
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
    tools: list[Tool] | None = None,
    model: str | Model | Agent | None = None,
    attempts: int | AgentAttempts = 1,
    submit: AgentSubmit = AgentSubmit(),
    on_continue: str | AgentContinue | None = None,
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
          Optionally, can also be an async function to call to determine whether
          the loop should continue (executed on every turn) and what message
          to play back.

    Returns:
        ReAct agent.
    """
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
        prompt_content = "\n\n".join(prompt_lines).format(submit=submit.name)
        system_message: ChatMessage | None = ChatMessageSystem(content=prompt_content)
    else:
        system_message = None

    # resolve on_continue
    if on_continue is None:
        on_continue = "If you believe you have completed the task, please call the `submit()` tool with your answer."
    if isinstance(on_continue, str):
        no_tools_continue_message = on_continue

        async def no_tools_continue(state: AgentState) -> bool | str:
            if state.output is None or not state.output.message.tool_calls:
                return no_tools_continue_message
            else:
                return True

        on_continue = no_tools_continue

    # validate that on_continue is async
    if not is_callable_coroutine(on_continue):
        raise ValueError("The on_continue function must be async.")

    # resolve attempts
    attempts = AgentAttempts(attempts) if isinstance(attempts, int) else attempts

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

    # helper to see if there is a submit tool call
    def submitted_answer(tool_calls: list[ToolCall] | None) -> str | None:
        for tool_call in tool_calls or []:
            if tool_call.function == submit.name and tool_call.parse_error is None:
                return str(tool_call.arguments["answer"])
        return None

    # resolve tools
    tools = tools or []
    tools.append(tool_with(submit_tool(), submit.name, submit.description))

    async def execute(state: AgentState) -> AgentState:
        # prepend system message if we have one
        if system_message:
            state.messages.insert(0, system_message)

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

                transcript().info("Agent terminated: model context window exceeded")
                break

            # check for a submission
            answer = submitted_answer(state.output.message.tool_calls)
            if answer is not None:
                # remove the tool call and set the output to the answer for scoring
                state.output.message.tool_calls = None
                state.output.completion = (
                    f"{state.output.completion}\n\n{answer}".strip()
                )

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

            # no submitted answer, call tools and evaluate whether we should continue
            else:
                if state.output.message.tool_calls:
                    # call tool functions
                    messages, output = await execute_tools(state.messages, tools)
                    state.messages.extend(messages)
                    if output:
                        state.output = output

                # check if we should continue....
                do_continue = await on_continue(state)
                if isinstance(do_continue, str):
                    state.messages.append(ChatMessageUser(content=do_continue))
                elif do_continue is False:
                    break

        return state

    if name is not None or description is not None:
        return agent_with(execute, name=name, description=description)
    else:
        return execute


async def _agent_generate(
    model: str | Model | Agent | None, state: AgentState, tools: list[Tool]
) -> AgentState:
    # convert model to agent
    if isinstance(model, str | Model) or model is None:
        model = _model_generate(model)

    # confirm we have a tools param
    agent_tool_info = parse_tool_info(model)
    if "tools" not in agent_tool_info.parameters.properties:
        raise ValueError(
            "Agent passed as model for react agent must have a tools parameter."
        )

    # call the agent
    return await model(state, tools)


def _model_generate(model: str | Model | None) -> Agent:
    async def generate(state: AgentState, tools: list[Tool]) -> AgentState:
        state.output = await get_model(model).generate(state.messages, tools)
        state.messages.append(state.output.message)
        return state

    return generate
