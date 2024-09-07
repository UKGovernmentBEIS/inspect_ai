from inspect_ai.model._call_tools import call_tools
from inspect_ai.model._chat_message import ChatMessageTool, ChatMessageUser
from inspect_ai.model._model import get_model
from inspect_ai.scorer._metric import ValueToFloat, value_to_float
from inspect_ai.scorer._score import score
from inspect_ai.tool._tool import Tool, ToolResult, tool
from inspect_ai.tool._tool_with import tool_with

from ._plan import Plan, plan
from ._prompt import system_message
from ._solver import Generate, Solver, solver
from ._task_state import TaskState
from ._use_tools import use_tools

DEFAULT_SYSTEM_PROMPT = """
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
DEFAULT_SUBMIT_TOOL_RESPONSE = "Your submission will be evaluated."


@plan
def basic_agent(
    *,
    tools: list[Tool] = [],
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    max_attempts: int = 1,
    score_value: ValueToFloat | None = None,
    incorrect_message: str = DEFAULT_INCORRECT_MESSAGE,
    continue_message: str = DEFAULT_CONTINUE_MESSAGE,
    submit_name: str = DEFAULT_SUBMIT_NAME,
    submit_description: str = DEFAULT_SUBMIT_DESCRIPTION,
) -> Plan:
    """Basic ReAct agent.

    Agent that runs a tool use loop until the model submits an answer using the
    `submit()` tool. Tailor the model's instructions using the `system_prompt`
    parameter. Use `max_attempts` to support additional submissions if the
    initial submission(s) are incorrect (submissions are evaluated using the task's
    main scorer, with a correct ("C") or numerical value of 1.0 indicating a
    correct answer).

    Note that when using the `basic_agent()`, you should always establish a boundary
    on model activity (e.g. setting the task `max_messages`) to prevent it from
    continuing on in a loop interminably.

    Args:
       tools (list[Tool]): Tools available for the agent.
       system_prompt (str): System prompt for agent.
       max_attempts (int): Maximum number of submissions to accept before terminating.
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

    Returns:
        Plan for agent.
    """

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

    # enable customisation of submit tool name/description
    submit_tool = tool_with(submit(), submit_name, submit_description)

    # resolve score_value function
    score_value_fn = score_value or value_to_float()

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
            # track attempts
            attempts = 0

            # main loop
            while True:
                # check for completed (if we hit a limit e.g. max_messages)
                if state.completed:
                    break

                # generate output and append assistant message
                state.output = await get_model().generate(state.messages, state.tools)
                state.messages.append(state.output.message)

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

                # no tool calls: model gave up without submitting
                else:
                    # urge the model to continue
                    state.messages.append(ChatMessageUser(content=continue_message))

            return state

        return solve

    # return plan
    return Plan(
        [
            system_message(system_prompt),
            use_tools(tools + [submit_tool]),
            basic_agent_loop(),
        ]
    )
