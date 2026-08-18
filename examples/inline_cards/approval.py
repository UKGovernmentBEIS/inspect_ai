"""Demo task for the inline tool-call approval card.

Runs a mockllm-driven react agent that fires one tool call requiring
human approval, then submits.

CLI:

    inspect eval examples/inline_cards/approval.py
    inspect eval examples/inline_cards/approval.py --acp-server

The first form exercises the in-proc Textual approval surface; the
second flips the eval into ACP-server mode so an attached ``inspect
acp`` client renders the inline :class:`_ApprovalCard` instead.
"""

from inspect_ai import Task, task
from inspect_ai.agent._react import react
from inspect_ai.agent._types import AgentSubmit
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import includes
from inspect_ai.tool import Tool, tool


@tool
def dangerous_action() -> Tool:
    async def execute(action: str) -> str:
        """Perform an action that needs human approval before running.

        Args:
            action: Free-form description of what to do.

        Returns:
            Confirmation message once the operator has approved.
        """
        return f"performed: {action}"

    return execute


@task
def approval_demo() -> Task:
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="dangerous_action",
                tool_arguments={"action": "rm -rf /tmp/example"},
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
                    "Use the dangerous_action tool to clean up /tmp/example, "
                    "then submit 'ok'."
                ),
                target=["ok"],
            )
        ],
        solver=react(
            tools=[dangerous_action()],
            submit=AgentSubmit(
                name="submit",
                description="Submit the final answer once the action has run.",
            ),
        ),
        scorer=includes(),
        approval="human",
        message_limit=10,
        model=model,
    )
