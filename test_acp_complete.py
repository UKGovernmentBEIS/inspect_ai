"""Tiny eval for manually exercising the ACP TUI's ``complete`` lifecycle pill.

Runs one react-loop sample with a custom submit tool that sleeps 20s
before finalising the answer. That window is the operator's chance to:

  inspect acp <eval-id>

…attach to the running session, watch the running → idle transitions,
then watch the pill flip to ``complete`` (and the composer go
read-only) the moment submit returns and the session tears down.

Usage:
    inspect eval test_acp_complete.py --model openai/gpt-5
    # in another terminal:
    inspect acp
"""

from __future__ import annotations

import asyncio

from inspect_ai import Task, task
from inspect_ai.agent import AgentSubmit, react
from inspect_ai.dataset import Sample
from inspect_ai.scorer import exact
from inspect_ai.tool import Tool, tool

_SUBMIT_DELAY_SECONDS = 20.0


@tool(name="submit")
def slow_submit() -> Tool:
    """Submit tool that sleeps before returning, so the operator can attach.

    Returns the ``answer`` verbatim (matching the default submit-tool
    contract) after a deliberate pause — the pause is the whole point;
    it gives the TUI time to observe the running → complete
    transition rather than seeing the session finish before they can
    attach.
    """

    async def execute(answer: str) -> str:
        """Submit an answer for evaluation.

        Args:
            answer: Final answer to submit.
        """
        await asyncio.sleep(_SUBMIT_DELAY_SECONDS)
        return answer

    return execute


@task
def acp_complete_test() -> Task:
    return Task(
        dataset=[
            Sample(
                input="What is 2 + 2? Answer with just the number.",
                target="4",
            )
        ],
        solver=react(
            name="acp_complete_test",
            submit=AgentSubmit(tool=slow_submit()),
        ),
        scorer=exact(),
    )
