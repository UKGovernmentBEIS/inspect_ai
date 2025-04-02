from test_helpers.tool_call_utils import get_tool_event
from test_helpers.utils import skip_if_no_anthropic, skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log._transcript import ModelEvent
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import think


def check_think_tool(description: str | None = None):
    task = Task(
        dataset=[
            Sample(
                input="Please use the think tool to think about something. Whne you are done with that, please repeat exactly what you thought about as your final answer."
            )
        ],
        solver=[use_tools(think(description=description)), generate()],
    )
    log = eval(task, model="anthropic/claude-3-5-haiku-latest")[0]
    assert log.status == "success"
    tool_event = get_tool_event(log)
    assert tool_event
    assert tool_event.function == "think"
    assert isinstance(tool_event.arguments["thought"], str)
    return log


@skip_if_no_anthropic
@skip_if_no_docker
def test_think_tool():
    check_think_tool()


@skip_if_no_anthropic
@skip_if_no_docker
def test_think_tool_description():
    description = "This is a tool you can use for thinking."
    log = check_think_tool(description)
    assert log.samples
    model_event = next(
        (event for event in log.samples[0].events if isinstance(event, ModelEvent)),
        None,
    )
    assert model_event.call.request["tools"][0]["description"] == description
