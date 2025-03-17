from logging import getLogger
from typing import Awaitable, Callable, cast

from inspect_ai._util._async import is_callable_coroutine
from inspect_ai._util.notgiven import NOT_GIVEN, NotGiven
from inspect_ai.model._cache import CachePolicy
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool, ChatMessageUser
from inspect_ai.model._model import get_model
from inspect_ai.scorer._metric import Score, ValueToFloat, value_to_float
from inspect_ai.scorer._score import score
from inspect_ai.tool._tool import Tool, ToolResult, tool
from inspect_ai.tool._tool_with import tool_with

from ._agent import Agent, AgentState, agent

logger = getLogger(__name__)

DEFAULT_SYSTEM_MESSAGE = """
You are a helpful assistant attempting to submit the correct answer. You have
several functions available to help with finding the answer. Each message
may perform one function call. You will see the result of the function right
after sending the message. If you need to perform multiple actions, you can
always send more messages with subsequent function calls. Do some reasoning
before your actions, describing what function calls you are going to use and
how they fit into your plan.

When you have completed the task and have an answer, call the {submit}()
function to report it.
"""

DEFAULT_INCORRECT_MESSAGE = """
Your submission was incorrect. Please proceed and attempt to find the correct answer.
"""
DEFAULT_CONTINUE_MESSAGE = "Please proceed to the next step using your best judgement."
DEFAULT_SUBMIT_NAME = "submit"
DEFAULT_SUBMIT_DESCRIPTION = "Submit an answer for evaluation."


@agent
def react(
    *,
    system_message: str | None | NotGiven = NOT_GIVEN,
    tools: list[Tool] | None = None,
    cache: bool | CachePolicy = False,
    max_attempts: int = 1,
    max_tool_output: int | None = None,
    score_value: ValueToFloat | None = None,
    incorrect_message: str
    | Callable[[AgentState, list[Score]], str | Awaitable[str]]
    | NotGiven = NOT_GIVEN,
    continue_message: str | NotGiven = NOT_GIVEN,
    submit_name: str | NotGiven = NOT_GIVEN,
    submit_description: str | NotGiven = NOT_GIVEN,
) -> Agent:
    """ReAct agent.

    Agent that runs a tool use loop until the model submits an answer using the
    `submit()` tool. Tailor the model's instructions by passing a `system_message`
    (the default `system_message` provides a basic ReAct prompt). Use `max_attempts`
    to support additional submissions if the initial submission(s) are incorrect.

    Submissions are evaluated using the task's main scorer, with value of 1.0
    indicating a correct answer. Scorer values are converted to float (e.g.
    "C" becomes 1.0) using the standard value_to_float() function. Provide an
    alternate conversion scheme as required via `score_value`.

    Args:
       system_message: Agent initialisation (defaults to basic ReAct prompt)
       tools: Tools available for the agent.
       cache: Caching behaviour for generate responses (defaults to no caching).
       max_attempts: Maximum number of submissions to accept before terminating.
       message_limit: Limit on messages in sample before terminating agent.
          If not specified, will use limit_messages defined for the task. If there is none
          defined for the task, 50 will be used as a default.
       token_limit: Limit on tokens used in sample before terminating agent.
       max_tool_output: Maximum output length (in bytes).
          Defaults to max_tool_output from active GenerateConfig.
       score_value: Function used to extract float from scores (defaults
          to standard value_to_float())
       incorrect_message: User message reply for an incorrect submission from the model.
          Alternatively, a function which returns a message (function may optionally be async)
       continue_message: User message to urge the model to continue when it
          doesn't make a tool call.
       submit_name: Name for tool used to make submissions
          (defaults to 'submit')
       submit_description: Description of submit tool (defaults to
          'Submit an answer for evaluation')

    Returns:
        Solver that impements the ReAct agent.
    """
    # resolve system message
    system_message = (
        DEFAULT_SYSTEM_MESSAGE
        if isinstance(system_message, NotGiven)
        else system_message
    )

    # resolve score_value function
    score_value_fn = score_value or value_to_float()

    # resolve messages
    if isinstance(incorrect_message, NotGiven):
        incorrect_message = DEFAULT_INCORRECT_MESSAGE
    if isinstance(continue_message, NotGiven):
        continue_message = DEFAULT_CONTINUE_MESSAGE
    if isinstance(submit_name, NotGiven):
        submit_name = DEFAULT_SUBMIT_NAME
    if isinstance(submit_description, NotGiven):
        submit_description = DEFAULT_SUBMIT_DESCRIPTION

    # submission tool
    @tool
    def submit() -> Tool:
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
                and result.function == submit_name
            ),
            None,
        )

    # resolve tools
    tools = tools or []
    tools.append(tool_with(submit(), submit_name, submit_description))

    ## TODO: system messages
    ## TODO: handle with_state business (with_state should take agent state, agent needs to not know about solver except in as_solver (or perhaps move that function to solver))
    ## TODO: limit would have to move into util inspect_ai.util [limit stuff]

    async def execute(state: AgentState) -> AgentState:
        # track attempts
        attempts = 0

        # main loop = will terminate after submit (subject to max_attempts)
        # or if a message or token limit is hit
        while True:
            # generate output and append assistant message
            state.output = await get_model().generate(
                input=state.messages, tools=tools, cache=cache
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
                messages, output = await execute_tools(
                    state.messages,
                    tools,
                    max_output=max_tool_output,
                )
                state.messages.extend(messages)
                if output:
                    state.output = output

                # was an answer submitted?
                answer = submission(messages)
                if answer:
                    # set the output to the answer for scoring
                    state.output.completion = answer

                    # exit if we are at max_attempts
                    attempts += 1
                    if attempts >= max_attempts:
                        break

                    # exit if the submission is successful
                    answer_scores = await score(state)
                    if score_value_fn(answer_scores[0].value) == 1.0:
                        break

                    # otherwise notify the model that it was incorrect and continue
                    else:
                        if is_callable_coroutine(incorrect_message):
                            response_message: str = await incorrect_message(
                                state, answer_scores
                            )  # type: ignore[misc,operator]
                        elif callable(incorrect_message):
                            response_message = cast(
                                str, incorrect_message(state, answer_scores)
                            )
                        else:
                            response_message = incorrect_message

                        state.messages.append(ChatMessageUser(content=response_message))

            # no tool calls, urge the model to continue
            else:
                state.messages.append(ChatMessageUser(content=continue_message))

        return state

    return execute
