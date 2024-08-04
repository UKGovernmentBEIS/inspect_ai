from random import randint
from typing import Literal

from test_helpers.tools import addition, raise_error, read_file
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_google,
    skip_if_no_groq,
    skip_if_no_mistral,
    skip_if_no_openai,
    skip_if_no_vertex,
)
from tool_call_utils import get_tool_call, get_tool_calls, get_tool_response

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import (
    ChatMessageUser,
    Model,
    get_model,
)
from inspect_ai.scorer import match
from inspect_ai.solver import (
    Generate,
    TaskState,
    generate,
    solver,
    system_message,
    use_tools,
)
from inspect_ai.tool import ToolFunction, tool

# we define 3 versions of addition so we can test the ability to force the
# the model to use a certain tool via tool_choice=ToolFunction()


# define some other tools to test forcing tool usage
@tool
def addition2():
    async def add(x: int, y: int):
        """
        Add two numbers.

        Args:
            x (int): First number to add.
            y (int): Second number to add.

        Returns:
            The sum of the two numbers.
        """
        return x + y

    return add


# define some other tools to test forcing tool usage
@tool
def addition3():
    async def add(x: int, y: int):
        """
        Add two numbers.

        Args:
            x (int): First number to add.
            y (int): Second number to add.

        Returns:
            The sum of the two numbers.
        """
        return x + y

    return add


def check_tools(model: Model, disable: list[str] = ["calls", "force", "none"]) -> None:
    if "calls" not in disable:
        check_tools_calls(model)
    if "force" not in disable:
        check_tools_force(model)
    if "none" not in disable:
        check_tools_none(model)


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
        scorer=match("any", numeric=True),
    )

    # evaluate the task
    log: list[EvalLog] = eval(task, model=model, model_args=model_args)

    # check that we got the answer right
    assert log[0].results and log[0].results.scores[0].metrics["accuracy"].value == 1

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
    check_tools("anthropic/claude-3-sonnet-20240229", disable=["none"])


@skip_if_no_mistral
def test_mistral_tools():
    check_tools("mistral/mistral-large-latest", disable=["force"])


@skip_if_no_groq
def test_groq_tools():
    check_tools("groq/mixtral-8x7b-32768")


@skip_if_no_google
def test_google_tools():
    check_tools("google/gemini-1.0-pro")


@skip_if_no_vertex
def test_vertex_tools():
    check_tools("vertex/gemini-1.5-flash")


@skip_if_no_openai
def test_dynamic_tools():
    @tool
    def color():
        async def execute():
            """Pick a random color.

            Returns:
              Color
            """
            return ["green", "red", "blue"][randint(0, 2)]

        return execute

    @tool
    def shape():
        async def execute():
            """Pick a random shape.

            Returns:
               Shape
            """
            return ["triangle", "circle", "square"][randint(0, 2)]

        return execute

    @solver
    def dynamic_tools():
        async def solve(state: TaskState, generate: Generate):
            state.tools = [color()]
            state = await generate(state)

            state.messages.append(ChatMessageUser(content="Pick a random shape."))
            state.tools = [shape()]
            return await generate(state)

        return solve

    task = Task(
        dataset=[Sample(input="Pick a random color.")],
        plan=dynamic_tools(),
        scorer=match(),
    )

    log = eval(task, model="openai/gpt-4")[0]
    assert log.samples
    messages = log.samples[0].messages
    tool_call = get_tool_call(messages, "color")
    assert tool_call is not None and tool_call.function == "color"
    messages.reverse()
    tool_call = get_tool_call(messages, "shape")
    assert tool_call is not None and tool_call.function == "shape"


@skip_if_no_openai
def test_tool_error():
    task = Task(
        dataset=[Sample(input="Please read the file 'foo.txt'")],
        plan=[use_tools([read_file()]), generate()],
        scorer=match(),
        sandbox="local",
    )
    log = eval(task, model="openai/gpt-4")[0]
    assert log.status == "success"
    assert log.samples
    messages = log.samples[0].messages
    tool_call = get_tool_call(messages, "read_file")
    assert tool_call
    response = get_tool_response(messages, tool_call)
    assert response
    assert response.error


@skip_if_no_openai
def test_tool_eval_error():
    task = Task(
        dataset=[Sample(input="Please raise an error.")],
        plan=[use_tools([raise_error()]), generate()],
        scorer=match(),
        sandbox="local",
    )
    log = eval(task, model="openai/gpt-4")[0]
    assert log.status == "error"


@skip_if_no_openai
def test_tool_calls():
    @tool
    def add():
        async def exec(x: int, y: int):
            """Add two numbers.

            When using this tool, be sure to call it at least
            three consecutive times to ensure the correct result.
            If you fail to call it three times and only call it
            one time it will give an incorrect result.

            Args:
                x (int): First number to add.
                y (int): Second number to add.

            Returns:
                The sum of the two numbers.
            """
            return x + y

        return exec

    def task(tool_calls: Literal["loop", "single", "none"]):
        return Task(
            dataset=[Sample(input="What is 1+1?", target="2")],
            plan=[
                system_message(
                    "When using the add tool, be sure to call it at least three consecutive times to ensure the correct result."
                ),
                use_tools([add()]),
                generate(tool_calls=tool_calls),
            ],
            scorer=match(),
        )

    def check_messages(log, predicate):
        assert log.status == "success"
        assert log.samples
        messages = log.samples[0].messages
        assert predicate(messages)

    # tool_calls == "loop"
    log = eval(task("loop"), model="openai/gpt-4")[0]
    check_messages(log, lambda m: len(get_tool_calls(m, "add")) > 1)

    # tool_calls == "single"
    log = eval(task("single"), model="openai/gpt-4")[0]
    check_messages(log, lambda m: len(get_tool_calls(m, "add")) == 1)

    # tool_calls == "none"
    log = eval(task("none"), model="openai/gpt-4")[0]
    check_messages(log, lambda m: get_tool_response(m, "add") is None)
