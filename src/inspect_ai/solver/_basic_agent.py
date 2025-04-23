from logging import getLogger
from typing import Awaitable, Callable, cast

from typing_extensions import TypedDict, Unpack

from inspect_ai._util._async import is_callable_coroutine
from inspect_ai.model._cache import CachePolicy
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool, ChatMessageUser
from inspect_ai.model._model import get_model
from inspect_ai.scorer._metric import Score, ValueToFloat, value_to_float
from inspect_ai.scorer._score import score
from inspect_ai.solver._chain import chain
from inspect_ai.tool._tool import Tool, ToolResult, tool
from inspect_ai.tool._tool_with import tool_with
from inspect_ai.util._limit import token_limit as create_token_limit

from ._prompt import system_message
from ._solver import Generate, Solver, solver
from ._task_state import TaskState
from ._use_tools import use_tools

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


class BasicAgentDeprecatedArgs(TypedDict, total=False):
    max_messages: int | None


@solver
def basic_agent(
    *,
    init: Solver | list[Solver] | None = None,
    tools: list[Tool] | Solver | None = None,
    cache: bool | CachePolicy = False,
    max_attempts: int = 1,
    message_limit: int | None = None,
    token_limit: int | None = None,
    max_tool_output: int | None = None,
    score_value: ValueToFloat | None = None,
    incorrect_message: str
    | Callable[
        [TaskState, list[Score]], str | Awaitable[str]
    ] = DEFAULT_INCORRECT_MESSAGE,
    continue_message: str = DEFAULT_CONTINUE_MESSAGE,
    submit_name: str = DEFAULT_SUBMIT_NAME,
    submit_description: str = DEFAULT_SUBMIT_DESCRIPTION,
    submit_append: bool = False,
    **kwargs: Unpack[BasicAgentDeprecatedArgs],
) -> Solver:
    """Basic ReAct agent.

    Agent that runs a tool use loop until the model submits an answer using the
    `submit()` tool. Tailor the model's instructions by passing a `system_message()`
    and/or other steps to `init` (if no `init` is specified then a default system
    message will be used). Use `max_attempts` to support additional submissions if
    the initial submission(s) are incorrect.

    Submissions are evaluated using the task's main scorer, with value of 1.0
    indicating a correct answer. Scorer values are converted to float (e.g.
    "C" becomes 1.0) using the standard value_to_float() function. Provide an
    alternate conversion scheme as required via `score_value`.

    Args:
       init: Agent initialisation (defaults to system_message with basic ReAct prompt)
       tools: Tools available for the agent. Either a list of tools or a Solver that
          can yield dynamic tools per-sample.
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
       submit_append: Append the submit tool output to the model completion
           text (defaults to `False`, which means the submission overwrites
           the model completion).
       **kwargs: Deprecated arguments for backward compatibility.

    Returns:
        Plan for agent.
    """
    # resolve deprecated
    for arg, value in kwargs.items():
        if arg == "max_messages":
            # deprecated, don't warn yet
            message_limit = int(cast(int, value))

    # resolve init
    if init is None:
        init = system_message(DEFAULT_SYSTEM_MESSAGE, submit=submit_name)
    init = init if isinstance(init, list) else [init]

    # resolve tools
    if tools is None:
        tools = []
    tools = tools if isinstance(tools, Solver) else use_tools(tools, append=True)

    # resolve score_value function
    score_value_fn = score_value or value_to_float()

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

    # solver that adds submission tool
    @solver
    def submit_tool() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            state.tools.append(tool_with(submit(), submit_name, submit_description))
            return state

        return solve

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

    # main agent loop
    @solver
    def basic_agent_loop() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            # resolve message_limit -- prefer parameter then fall back to task
            # (if there is no message_limit then default to 50)
            state.message_limit = message_limit or state.message_limit or 50

            # track attempts
            attempts = 0

            with create_token_limit(token_limit):
                # main loop
                while not state.completed:
                    # generate output and append assistant message
                    state.output = await get_model().generate(
                        input=state.messages, tools=state.tools, cache=cache
                    )
                    state.messages.append(state.output.message)

                    # check for context window overflow
                    if state.output.stop_reason == "model_length":
                        from inspect_ai.log._transcript import transcript

                        transcript().info(
                            "Agent terminated: model context window exceeded"
                        )
                        break

                    # resolve tools calls (if any)
                    if state.output.message.tool_calls:
                        # execute tool functions
                        tool_results, _ = await execute_tools(
                            [state.output.message],
                            state.tools,
                            max_output=max_tool_output,
                        )
                        state.messages.extend(tool_results)

                        # was an answer submitted?
                        answer = submission(tool_results)
                        if answer:
                            if submit_append:
                                state.output.completion = (
                                    f"{state.output.completion}\n\n{answer}".strip()
                                )
                            else:
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

                                state.messages.append(
                                    ChatMessageUser(content=response_message)
                                )

                    # no tool calls, urge the model to continue
                    else:
                        state.messages.append(ChatMessageUser(content=continue_message))

            return state

        return solve

    # return chain
    return chain(
        init
        + [
            tools,
            submit_tool(),
            basic_agent_loop(),
        ]
    )
