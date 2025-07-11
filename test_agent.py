from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import ContentData
from inspect_ai.scorer import Score, Scorer, Target, accuracy, scorer
from inspect_ai.solver import TaskState, basic_agent
from inspect_ai.tool import Tool, tool


@tool
def view_pdf() -> Tool:
    """Tool for viewing PDFs from the internet."""

    async def execute(url: str) -> str:
        """
        Use this tool to view a PDF file from the internet.

        Args:
            url: The URL to fetch the PDF from.
        """
        return ContentData(
            data={
                "type": "document",
                "source": {
                    "type": "url",
                    "url": url,
                },
            }
        )

    return execute


@scorer(metrics=[accuracy()])
def dummy_scorer() -> Scorer:
    async def _scorer(state: TaskState, target: Target):
        return Score(
            value=1 if "Marius Hobbhahn" in state.output.completion else 0,
            answer=state.output.completion,
        )

    return _scorer


@task
def example_task():
    return Task(
        dataset=[
            Sample(
                "Please fetch the author list of this paper https://arxiv.org/pdf/2412.04984"
            )
        ],
        solver=basic_agent(
            tools=[
                view_pdf(),
            ],
        ),
        scorer=[dummy_scorer()],
        message_limit=10,
        model="anthropic/claude-sonnet-4-20250514",
    )
