from test_helpers.utils import skip_if_no_openai, skip_if_no_openai_reasoning_summaries

from inspect_ai import Task, eval
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.model import ContentReasoning
from inspect_ai.tool import Tool, tool


@skip_if_no_openai
@skip_if_no_openai_reasoning_summaries
def test_openai_reasoning_summary():
    log = eval(
        Task(dataset=[Sample(input="Solve 3*x^3-5*x=1")]),
        model="openai/o4-mini",
        reasoning_summary="auto",
    )[0]
    assert log.status == "success"
    assert log.samples
    content = log.samples[0].output.message.content
    assert isinstance(content, list)
    assert isinstance(content[0], ContentReasoning)


@skip_if_no_openai
@skip_if_no_openai_reasoning_summaries
def test_openai_reasoning_summary_playback():
    @tool
    def validate() -> Tool:
        async def execute(answer: str) -> bool:
            """Validate the answer to a mathematical question.

            Args:
                answer: Answer to validate
            """
            return True

        return execute

    log = eval(
        Task(
            dataset=[
                Sample(
                    input="Solve 3*x^3-5*x=1, then call the validate() tool validate your answer. Then after that, solve x^2 - 5x + 6 = 0 and once again call the validate() tool to validate your answer."
                )
            ],
            solver=react(tools=[validate()]),
        ),
        model="openai/o4-mini",
        reasoning_summary="auto",
    )[0]
    assert log.status == "success"
    assert log.samples
    content = log.samples[0].output.message.content
    assert isinstance(content, list)
    assert isinstance(content[0], ContentReasoning)
