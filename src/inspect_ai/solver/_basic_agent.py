from logging import getLogger
from typing import cast

from typing_extensions import TypedDict, Unpack

from inspect_ai.model._cache import CachePolicy
from inspect_ai.model._call_tools import call_tools
from inspect_ai.model._chat_message import ChatMessageTool, ChatMessageUser
from inspect_ai.model._model import get_model
from inspect_ai.scorer._metric import ValueToFloat, value_to_float
from inspect_ai.scorer._score import score
from inspect_ai.solver._chain import chain
from inspect_ai.tool._tool import Tool, ToolResult, tool
from inspect_ai.tool._tool_with import tool_with

from ._prompt import system_message
from ._solver import Generate, Solver, solver
from ._task_state import TaskState
from ._use_tools import use_tools

logger = getLogger(__name__)

DEFAULT_SYSTEM_MESSAGE = """
You are a helpful assistant attempting to submit the correct answer. You have
several functions available to help with finding the answer. Each message may
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
    score_value: ValueToFloat | None = None,
    incorrect_message: str = DEFAULT_INCORRECT_MESSAGE,
    continue_message: str = DEFAULT_CONTINUE_MESSAGE,
    submit_name: str = DEFAULT_SUBMIT_NAME,
    submit_description: str = DEFAULT_SUBMIT_DESCRIPTION,
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
       init: (Solver | list[Solver] | None): Agent initialisation
         (defaults to system_message with basic ReAct prompt)
       tools (list[Tool | ToolDef] | Solver | None): Tools available for the agent. Either a
         list of tools or a Solver that can yield dynamic tools per-sample.
       cache: (bool | CachePolicy): Caching behaviour for generate responses
         (defaults to no caching).
       max_attempts (int): Maximum number of submissions to accept before terminating.
       message_limit (int): Limit on messages in sample before terminating agent.
          If not specified, will use limit_messages defined for the task. If there is none
          defined for the task, 50 will be used as a default.
       token_limit (int): Limit on tokens used in sample before terminating agent.
       score_value (ValueToFloat): Function used to extract float from scores (defaults
         to standard value_to_float())
       incorrect_message (str): User message reply for an incorrect submission from
         the model.
       continue_message (str): User message to urge the model to continue when it
         doesn't make a tool call.
       submit_name (str): Name for tool used to make submissions
        (defaults to 'submit')
       submit_description (str): Description of submit tool (defaults to
        'Submit an answer for evaluation')
       **kwargs (Any): Deprecated arguments for backward compatibility.

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
    tools = tools if isinstance(tools, Solver) else use_tools(tools)

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
    def submission(tool_results: list[ChatMessageTool]) -> str | None:
        return next(
            (result.text for result in tool_results if result.function == submit_name),
            None,
        )

    # main agent loop
    @solver
    def basic_agent_loop() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            # resolve message_limit -- prefer parameter then fall back to task
            # (if there is no message_limit then default to 50)
            state.message_limit = message_limit or state.message_limit or 50

            # resolve token limit
            state.token_limit = token_limit or state.token_limit

            # track attempts
            attempts = 0

            # main loop (state.completed checks message_limit and token_limit)
            while not state.completed:
                # generate output and append assistant message
                state.output = await get_model().generate(
                    input=state.messages, tools=state.tools, cache=cache
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
                    tool_results = await call_tools(state.output.message, state.tools)
                    state.messages.extend(tool_results)

                    # was an answer submitted?
                    answer = submission(tool_results)
                    if answer:
                        # set the output to the answer for scoring
                        state.output.completion = answer

                        # score it
                        answer_scores = await score(state)
                        if score_value_fn(answer_scores[0].value) == 1.0:
                            break

                        # exit if we are at max_attempts
                        attempts += 1
                        if attempts >= max_attempts:
                            break
                        # otherwise notify the model that it was incorrect and continue
                        else:
                            state.messages.append(
                                ChatMessageUser(content=incorrect_message)
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
