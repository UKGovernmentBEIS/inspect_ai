"""Smoke regression: adjacent event timing semantics remain intact."""

from inspect_ai import Task
from inspect_ai import eval as inspect_eval
from inspect_ai.dataset import Sample
from inspect_ai.event._subtask import SubtaskEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import tool


@tool
def slow_tool():
    """Double an integer slowly."""

    async def execute(x: int) -> int:
        """Double an integer slowly.

        Args:
            x: Integer to double.
        """
        import anyio

        await anyio.sleep(0.01)
        return x * 2

    return execute


def test_tool_event_working_time_set_and_nonnegative() -> None:
    calls = [0]

    def custom_outputs(
        _input: object, _tools: object, _tool_choice: object, _config: object
    ) -> ModelOutput:
        calls[0] += 1
        if calls[0] == 1:
            return ModelOutput.for_tool_call("mockllm", "slow_tool", {"x": 2})
        return ModelOutput.from_content("mockllm", "done")

    log = inspect_eval(
        Task(dataset=[Sample(input="hi")], solver=[use_tools(slow_tool()), generate()]),
        model="mockllm/test",
        model_args={"custom_outputs": custom_outputs},
    )[0]

    assert log.samples is not None
    tool_events = [
        event for event in log.samples[0].events if isinstance(event, ToolEvent)
    ]
    assert tool_events
    for event in tool_events:
        assert event.completed is not None
        assert event.working_time is not None
        assert event.working_time >= 0


async def test_subtask_event_working_time_set_and_nonnegative() -> None:
    from inspect_ai.log._transcript import Transcript, init_transcript
    from inspect_ai.util import subtask

    @subtask
    async def my_subtask(x: int) -> int:
        import anyio

        await anyio.sleep(0.01)
        return x

    transcript = Transcript()
    init_transcript(transcript)
    await my_subtask(5)

    subtask_events = [
        event for event in transcript.events if isinstance(event, SubtaskEvent)
    ]
    assert subtask_events
    for event in subtask_events:
        assert event.completed is not None
        assert event.working_time is not None
        assert event.working_time >= 0
