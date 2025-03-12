from typing import Awaitable, Callable, cast

from typing_extensions import TypedDict, Unpack

from inspect_ai._util.notgiven import NOT_GIVEN, NotGiven
from inspect_ai.agent._react import react
from inspect_ai.model._cache import CachePolicy
from inspect_ai.scorer._metric import Score, ValueToFloat
from inspect_ai.tool._tool import Tool

from ._solver import Solver, solver
from ._task_state import TaskState


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

    return react(
        init=init,
        tools=tools,
        cache=cache,
        max_attempts=max_attempts,
        message_limit=message_limit,
        token_limit=token_limit,
        max_tool_output=max_tool_output,
        score_value=score_value,
        incorrect_message=incorrect_message,
        continue_message=continue_message,
        submit_name=submit_name,
        submit_description=submit_description,
    )
