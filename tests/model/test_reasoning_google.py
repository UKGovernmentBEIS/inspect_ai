from test_helpers.utils import skip_if_no_google

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentReasoning
from inspect_ai.dataset import Sample
from inspect_ai.log._log import EvalLog
from inspect_ai.model import get_model
from inspect_ai.tool import Tool, ToolFunction, tool


@skip_if_no_google
def test_google_reasoning_tokens():
    # run eval w/ reasoning tokens
    task = Task(dataset=[Sample(input="Solve 3*x^3-5*x=1")])
    log = eval(
        task,
        model="google/gemini-2.5-flash",
        reasoning_tokens=1024,
    )[0]
    assert log.status == "success"

    # confirm thinking budget was set and reasoning was done
    log_json = log.model_dump_json(indent=2)
    assert '"thinkingBudget": 1024' in log_json

    check_for_reasoning(log)


@skip_if_no_google
def test_google_reasoning_effort():
    # run eval w/ reasoning tokens
    task = Task(dataset=[Sample(input="Solve 3*x^3-5*x=1")])
    log = eval(
        task,
        model="google/gemini-3.1-pro-preview",
        reasoning_effort="low",
    )[0]
    assert log.status == "success"

    # confirm thinking budget was set and reasoning was done
    log_json = log.model_dump_json(indent=2)
    assert '"thinkingLevel": "LOW"' in log_json

    check_for_reasoning(log)


GEMINI_4_ARGON = "google/gemini-4-argon"


@skip_if_no_google
def test_google_gemini_4_argon_default() -> None:
    task = Task(dataset=[Sample(input="Solve 3*x^3-5*x=1")])
    log = eval(task, model=GEMINI_4_ARGON)[0]
    assert log.status == "success"
    assert "thinkingLevel" not in log.model_dump_json()


@skip_if_no_google
def test_google_gemini_4_argon_reasoning_effort_low() -> None:
    task = Task(dataset=[Sample(input="Solve 3*x^3-5*x=1")])
    log = eval(task, model=GEMINI_4_ARGON, reasoning_effort="low")[0]
    assert log.status == "success"
    assert '"thinkingLevel": "LOW"' in log.model_dump_json(indent=2)


@skip_if_no_google
def test_google_gemini_4_argon_reasoning_effort_minimal() -> None:
    # the API rejects MINIMAL for this model, so it is sent as LOW
    task = Task(dataset=[Sample(input="Solve 3*x^3-5*x=1")])
    log = eval(task, model=GEMINI_4_ARGON, reasoning_effort="minimal")[0]
    assert log.status == "success"
    assert '"thinkingLevel": "LOW"' in log.model_dump_json(indent=2)


@tool
def add() -> Tool:
    async def execute(x: int, y: int) -> int:
        """Add two numbers.

        Args:
            x: First number to add.
            y: Second number to add.

        Returns:
            The sum of the two numbers.
        """
        return x + y

    return execute


@skip_if_no_google
async def test_google_gemini_4_argon_tool_call() -> None:
    output = await get_model(GEMINI_4_ARGON).generate(
        "Use the add tool to add 2 and 3.",
        tools=[add()],
        tool_choice=ToolFunction(name="add"),
    )
    assert output.message.tool_calls
    assert output.message.tool_calls[0].function == "add"
    assert output.message.tool_calls[0].arguments == {"x": 2, "y": 3}


def check_for_reasoning(log: EvalLog) -> None:
    assert log.samples
    output = log.samples[0].output
    assert output.usage
    assert output.usage.reasoning_tokens

    # confirm we captured the reasoning content block
    content = output.message.content
    if isinstance(content, ContentReasoning):
        pass
    elif isinstance(content, list):
        assert any(isinstance(item, ContentReasoning) for item in content), (
            "List should contain at least one ContentReasoning object"
        )
    else:
        assert False, f"Content should be ContentReasoning or list, got {type(content)}"
