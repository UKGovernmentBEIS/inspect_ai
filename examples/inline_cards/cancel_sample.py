"""Demo task for sample cancellation (``^N``).

Runs a mockllm-driven react agent that fires a very long-running
tool (10 min sleep). The operator presses ``^N`` mid-tool to
surface the inline :class:`_CancelCard`; picking ``Score`` fires
``inspect/cancel_sample`` and the sample ends cleanly (scoring
runs on whatever the agent has produced so far). ``Error`` ends
the sample as an error; ``Back`` dismisses the card and lets the
agent continue.

Unlike approval / elicitation, the agent keeps running while the
operator deliberates here. The cancel card mounts in the composer's
slot (below the plan strip, above the footer) so it stays visible
regardless of where the operator has scrolled the transcript.

CLI:

    inspect eval examples/inline_cards/cancel_sample.py
    inspect eval examples/inline_cards/cancel_sample.py --acp-server
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
def slow_busy_work() -> Tool:
    async def execute(seconds: int) -> str:
        """Pretend to be busy for a long time, then return.

        The agent keeps the operator on the hook for ``seconds``
        seconds before this tool finishes; in the meantime ``^N``
        in the TUI fires the inline cancel card.

        Args:
            seconds: How long to sleep.

        Returns:
            Completion message after the sleep finishes.
        """
        await anyio.sleep(seconds)
        return f"slept for {seconds} seconds"

    return execute


@task
def cancel_sample_demo() -> Task:
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="slow_busy_work",
                tool_arguments={"seconds": 600},
            ),
            # Reached only if the operator picks Back rather than
            # Score / Error — the sample-cancel paths short-circuit
            # the agent loop before the next model call.
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
                    "Call slow_busy_work with seconds=600 (the operator will "
                    "interrupt the sample), then submit 'ok'."
                ),
                target=["ok"],
            )
        ],
        solver=react(
            tools=[slow_busy_work()],
            submit=AgentSubmit(
                name="submit",
                description="Submit the final answer (only reached if the operator picks Back).",
            ),
        ),
        scorer=includes(),
        message_limit=10,
        model=model,
    )
