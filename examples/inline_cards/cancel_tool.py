"""Demo task for tool-call cancellation (``^L``).

Runs a mockllm-driven react agent that fires a long-running tool
(60s sleep). The operator presses ``^L`` mid-tool to fire
``inspect/cancel_tool_call``; the sleep raises
``CancelledError``, the agent receives the failure status, and the
mock model proceeds to submit.

CLI:

    inspect eval examples/inline_cards/cancel_tool.py
    inspect eval examples/inline_cards/cancel_tool.py --acp-server
"""

import anyio

from inspect_ai import Task, task
from inspect_ai.agent._react import react
from inspect_ai.agent._types import AgentSubmit
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import includes
from inspect_ai.tool import Tool, tool


@tool
def long_running_task() -> Tool:
    async def execute(seconds: int) -> str:
        """Sleep for the requested duration, then return.

        Use this when a task legitimately needs to wait — e.g.
        polling an external service. Operators can cancel a running
        invocation with ``^L`` in the TUI.

        Args:
            seconds: How long to sleep.

        Returns:
            Completion message after the sleep finishes.
        """
        await anyio.sleep(seconds)
        return f"slept for {seconds} seconds"

    return execute


@task
def cancel_tool_demo() -> Task:
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="long_running_task",
                tool_arguments={"seconds": 60},
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "ok"},
            ),
        ],
    )

    return Task(
        dataset=[
            Sample(
                input=(
                    "Call long_running_task with seconds=60 (the operator "
                    "will interrupt it), then submit 'ok'."
                ),
                target=["ok"],
            )
        ],
        solver=react(
            tools=[long_running_task()],
            submit=AgentSubmit(
                name="submit",
                description="Submit the final answer after the tool returns or is cancelled.",
            ),
        ),
        scorer=includes(),
        message_limit=10,
        model=model,
    )
