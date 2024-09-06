from inspect_ai.model._call_tools import call_tools
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._model import get_model
from inspect_ai.scorer._metric import ValueToFloat, value_to_float
from inspect_ai.scorer._score import score
from inspect_ai.tool._tool import Tool, ToolResult, tool
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_with import tool_with
from inspect_ai.util import store

from ._plan import Plan, plan
from ._prompt import system_message
from ._solver import Generate, Solver
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

When you have completed the task and have a result, call the {submit}() function to
communicate it.
"""


DEFAULT_INCORRECT_MESSAGE = """
Your submission was incorrect. Please proceed and attempt to find the correct answer."
"""

DEFAULT_CONTINUE_MESSAGE = "Please proceed to the next step using your best judgement."

DEFAULT_SUBMIT_TOOL_NAME = "submit"
DEFAULT_SUBMIT_TOOL_DESCRIPTION = "Submit an answer for evaluation."
DEFAULT_SUBMIT_TOOL_RESPONSE = "Your submission will be evaluated for correctness."


@plan
def basic_agent(
    *,
    tools: list[Tool] = [],
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    max_attempts: int = 1,
    score_value: ValueToFloat | None = None,
    incorrect_message: str = DEFAULT_INCORRECT_MESSAGE,
    continue_message: str = DEFAULT_CONTINUE_MESSAGE,
    submit_tool_name: str = DEFAULT_SUBMIT_TOOL_NAME,
    submit_tool_description: str = DEFAULT_SUBMIT_TOOL_DESCRIPTION,
    submit_tool_response: str = DEFAULT_SUBMIT_TOOL_RESPONSE,
) -> Plan:
    """Docs

    Note that you should have a termination condition!

    Infinite attempts (max_messages or max_tokens)

    """
    # state shared between submit tool and agent_loop
    ANSWER = "basic_agent:answer"

    # submission tool
    @tool
    def submit() -> Tool:
        async def execute(answer: str) -> ToolResult:
            """Submit an answer for evaluation.

            Args:
              answer (str): Submitted answer
            """
            # set the answer (it will evaluated by the main loop)
            store().set(ANSWER, answer)

            # thank the model for its submission!
            return submit_tool_response

        return execute

    # enable customisation of submit tool name/description
    submit_tool = [tool_with(submit(), submit_tool_name, submit_tool_description)]

    # resolve score_value function
    score_value_fn = score_value or value_to_float()

    # helper to check if a submission was attempted
    def answer_submitted(tool_calls: list[ToolCall]) -> bool:
        return any([tool for tool in tool_calls if tool.function == "submit"])

    # main agent loop
    def agent_loop() -> Solver:
        # get a reference to the evaluated model
        model = get_model()

        async def solve(state: TaskState, generate: Generate) -> TaskState:
            # track attempts
            attempts = 0

            # main loop
            while True:
                # check for completed (if we hit a limit e.g. max_messages)
                if state.completed:
                    break

                # generate output and append assistant message
                state.output = await model.generate(state.messages, state.tools)
                state.messages.append(state.output.message)

                # resolve tools calls (if any)
                if state.output.message.tool_calls:
                    # call tool functions
                    state.messages.extend(
                        await call_tools(state.output.message, state.tools)
                    )

                    # was an answer submitted?
                    if answer_submitted(state.output.message.tool_calls):
                        # get the answer and score it (exit if correct)
                        answer = store().get(ANSWER)
                        state.output.completion = answer
                        answer_scores = await score(state)
                        if score_value_fn(answer_scores[0].value) == 1.0:
                            break

                        # check attempts
                        attempts += 1
                        if attempts >= max_attempts:
                            break

                        # notify the model that it was incorrect
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
        [system_message(system_prompt), use_tools(tools + [submit_tool]), agent_loop()]
    )
