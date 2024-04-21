from utils import (
    addition,
    skip_if_no_anthropic,
    skip_if_no_google,
    skip_if_no_mistral,
    skip_if_no_openai,
)

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    Model,
    ToolCall,
    ToolFunction,
    get_model,
)
from inspect_ai.scorer import match
from inspect_ai.solver import generate, tool, use_tools

# we define 3 versions of addition so we can test the ability to force the
# the model to use a certain tool via tool_choice=ToolFunction()


# define some other tools to test forcing tool usage
@tool(
    prompt="""
    If you are given a math problem of any kind,
    please use the addition tool to compute the result.
"""
)
def addition2():
    async def add(x: int, y: int):
        """
        Tool for adding two numbers.

        Args:
            x (int): First number to add.
            y (int): Second number to add.

        Returns:
            The sum of the two numbers.
        """
        return x + y

    return add


# define some other tools to test forcing tool usage
@tool(
    prompt="""
    If you are given a math problem of any kind,
    please use the addition tool to compute the result.
"""
)
def addition3():
    async def add(x: int, y: int):
        """
        Tool for adding two numbers.

        Args:
            x (int): First number to add.
            y (int): Second number to add.

        Returns:
            The sum of the two numbers.
        """
        return x + y

    return add


def check_tools(model: Model, **model_args) -> None:
    check_tools_calls(model, **model_args)
    check_tools_none(model, **model_args)
    check_tools_force(model, **model_args)


addition_dataset = [
    Sample(
        input="What is 1 + 1?", target=["2", "2.0", "Two"], metadata={"color": "red"}
    )
]


def check_tools_calls(model: Model, **model_args) -> None:
    model = get_model(model)
    task = Task(
        dataset=addition_dataset,
        plan=[use_tools(addition()), generate()],
        scorer=match(),
    )

    # evaluate the task
    log: list[EvalLog] = eval(task, model=model, model_args=model_args)

    # check that we got the answer right
    assert log[0].results and log[0].results.metrics["accuracy"].value == 1

    # check that there is a tool_call
    assert log[0].samples
    messages = log[0].samples[0].messages
    tool_call = get_tool_call(messages, "addition")
    assert tool_call

    # check that there is a tool response for this call
    assert get_tool_response(messages, tool_call)


def check_tools_none(model: Model, **model_args) -> None:
    model = get_model(model)
    task = Task(
        dataset=addition_dataset,
        plan=[use_tools(addition(), tool_choice="none"), generate()],
        scorer=match(),
    )

    # evaluate the task
    log: list[EvalLog] = eval(task, model=model, model_args=model_args)

    # confirm no tool calls
    assert log[0].samples
    messages = log[0].samples[0].messages
    tool_call = get_tool_call(messages, "addition")
    assert tool_call is None


def check_tools_force(model: Model, **model_args) -> None:
    model = get_model(model)
    task = Task(
        dataset=addition_dataset,
        plan=[
            use_tools(
                [addition(), addition2(), addition3()],
                tool_choice=ToolFunction(name="addition2"),
            ),
            generate(),
        ],
        scorer=match(),
    )

    # evaluate the task
    log: list[EvalLog] = eval(task, model=model, model_args=model_args)

    # confirm we called the right tool
    assert log[0].samples
    messages = log[0].samples[0].messages
    tool_call = get_tool_call(messages, "addition2")
    assert tool_call is not None and tool_call.function == "addition2"


@skip_if_no_openai
def test_openai_tools():
    check_tools("openai/gpt-4")


@skip_if_no_anthropic
def test_anthropic_tools():
    check_tools("anthropic/claude-3-sonnet-20240229", tools_beta=False)
    check_tools("anthropic/claude-3-sonnet-20240229", tools_beta=True)


@skip_if_no_mistral
def test_mistral_tools():
    check_tools("mistral/mistral-large-latest")


@skip_if_no_google
def test_google_tools():
    check_tools("google/gemini-1.0-pro")


def get_tool_call(messages: list[ChatMessage], tool: str) -> ToolCall | None:
    assistant_messages = [
        message for message in messages if isinstance(message, ChatMessageAssistant)
    ]
    tool_call_message = next(
        (
            message
            for message in assistant_messages
            if message.tool_calls and len(message.tool_calls)
        ),
        None,
    )
    if tool_call_message:
        return next(
            (
                tool_call
                for tool_call in (tool_call_message.tool_calls or [])
                if tool_call.function == tool
            ),
            None,
        )
    else:
        return None


def get_tool_response(messages: list[ChatMessage], tool_call: ToolCall) -> str | None:
    tool_messages = [
        message for message in messages if isinstance(message, ChatMessageTool)
    ]
    tool_response = next(
        (message for message in tool_messages if message.tool_call_id == tool_call.id),
        None,
    )
    if tool_response:
        return tool_response.text
    else:
        return None
