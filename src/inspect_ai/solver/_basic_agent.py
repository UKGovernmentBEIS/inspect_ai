from copy import copy
from logging import getLogger
from typing import Awaitable, Callable, cast

from typing_extensions import TypedDict, Unpack

from inspect_ai._util._async import is_callable_coroutine
from inspect_ai._util.notgiven import NOT_GIVEN, NotGiven
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._react import DEFAULT_SYSTEM_MESSAGE, react
from inspect_ai.model._cache import CachePolicy
from inspect_ai.scorer._metric import Score, ValueToFloat
from inspect_ai.tool._tool import Tool

from ._as_solver import as_solver
from ._chain import chain
from ._prompt import system_message
from ._solver import Generate, Solver, solver
from ._task_state import TaskState, sample_state
from ._use_tools import use_tools

logger = getLogger(__name__)


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
    | Callable[[TaskState, list[Score]], str | Awaitable[str]]
    | NotGiven = NOT_GIVEN,
    continue_message: str | NotGiven = NOT_GIVEN,
    submit_name: str | NotGiven = NOT_GIVEN,
    submit_description: str | NotGiven = NOT_GIVEN,
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

    # main agent loop
    @solver
    def agent_loop() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            # resolve message_limit -- prefer parameter then fall back to task
            # (if there is no message_limit then default to 50)
            state.message_limit = message_limit or state.message_limit or 50

            # resolve token limit
            state.token_limit = token_limit or state.token_limit

            # create react agent and bridge to solver interface
            react_agent = as_solver(
                react(
                    system_message=None,
                    tools=state.tools,
                    cache=cache,
                    max_attempts=max_attempts,
                    max_tool_output=max_tool_output,
                    score_value=score_value,
                    incorrect_message=agent_incorrect_message(incorrect_message),
                    continue_message=continue_message,
                    submit_name=submit_name,
                    submit_description=submit_description,
                )
            )

            # run agent
            return await react_agent(state, generate)

        return solve

    # return chain
    return chain(init, tools, agent_loop())


def agent_incorrect_message(
    incorrect_message: str
    | Callable[[TaskState, list[Score]], str | Awaitable[str]]
    | NotGiven,
) -> str | Callable[[AgentState, list[Score]], Awaitable[str]] | NotGiven:
    if callable(incorrect_message):

        async def _agent_incorrect_message(
            state: AgentState, scores: list[Score]
        ) -> str:
            task_state = sample_state()
            if task_state is None:
                raise RuntimeError(
                    "No task state available for resolution of incorrect_message"
                )
            task_state = copy(task_state)
            task_state.messages = state.messages
            if not state.output.empty:
                task_state.output = state.output
            if is_callable_coroutine(incorrect_message):
                message: str = await incorrect_message(task_state, scores)  # type: ignore[misc]
            else:
                message = incorrect_message(task_state, scores)  # type: ignore[assignment]
            return message

        return _agent_incorrect_message

    else:
        return incorrect_message
