"""Deepagent demo for exercising the agent() dispatch tool and viewer rendering.

Each subagent has its own mockllm instance so its scripted trajectory is
self-contained and event ordering is deterministic regardless of dispatch
order. The parent has a fourth mockllm that orchestrates dispatch.

The scripted ModelOutputs include natural assistant narration alongside each
tool call (rather than mockllm's default placeholder text) so the viewer
shows assistant messages the same way it would for a real frontier model.

Run:
    inspect eval examples/deepagent_demo.py

Then open the resulting log in Inspect View to see nested agent spans,
agent() tool calls labeled "agent: research" / "agent: plan" /
"agent: general", and each subagent's interior tool-call trajectory.
"""

import uuid
from typing import Any

from inspect_ai import Task, task
from inspect_ai._util.content import ContentText
from inspect_ai.agent import deepagent, general, plan, research
from inspect_ai.dataset import Sample
from inspect_ai.model import Model, ModelOutput, get_model
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._model_output import ChatCompletionChoice
from inspect_ai.tool import ToolCall, think


def _output(narration: str, *tool_calls: ToolCall) -> ModelOutput:
    """Build a ModelOutput with rich text content + zero-or-more tool calls.

    Uses a typed `[ContentText(...)]` content list so the message shape
    matches what a real frontier model would emit.
    """
    return ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content=[ContentText(text=narration)],
                    model="mockllm/model",
                    source="generate",
                    tool_calls=list(tool_calls) if tool_calls else None,
                ),
                stop_reason="tool_calls" if tool_calls else "stop",
            )
        ],
    )


def _call(name: str, **arguments: Any) -> ToolCall:
    return ToolCall(
        id=f"call_{uuid.uuid4().hex[:8]}",
        function=name,
        arguments=arguments,
    )


def _research_model() -> Model:
    return get_model(
        "mockllm/model",
        custom_outputs=[
            _output(
                "Starting with the three signals. Let me think through what to "
                "look at first.",
                _call("think", thought="Need baseline metrics for A, B, and C."),
            ),
            _output(
                "Now cross-referencing those signals against historical norms.",
                _call(
                    "think",
                    thought="Comparing current values to last quarter's targets.",
                ),
            ),
            _output(
                "I have the numbers and have validated them. Reporting back.",
                _call(
                    "submit",
                    answer=(
                        "Baseline metrics — A=42, B=17, C=91. A and B are below target."
                    ),
                ),
            ),
        ],
    )


def _plan_model() -> Model:
    return get_model(
        "mockllm/model",
        custom_outputs=[
            _output(
                "Two signals need work. Let me weigh cost vs impact for each.",
                _call(
                    "think",
                    thought="A and B need work; weighing cost vs impact of each fix.",
                ),
            ),
            _output(
                "Tuning A is low-risk and quick. Compressing B is more involved "
                "but higher-impact.",
                _call(
                    "think",
                    thought=(
                        "Tuning A is low-risk; compressing B is medium-risk but "
                        "high-impact."
                    ),
                ),
            ),
            _output(
                "Plan is ready. Returning the recommended sequence.",
                _call(
                    "submit",
                    answer=(
                        "Plan: (1) tune A's threshold to lift it above target, "
                        "(2) compress B's payload to halve latency, "
                        "(3) leave C — already healthy."
                    ),
                ),
            ),
        ],
    )


def _general_model() -> Model:
    return get_model(
        "mockllm/model",
        custom_outputs=[
            _output(
                "Starting with A — tuning the threshold per the plan.",
                _call("think", thought="Tuning A's threshold first."),
            ),
            _output(
                "A is at target. Moving on to B's payload compression.",
                _call("think", thought="Now compressing B's payload."),
            ),
            _output(
                "Both changes applied. Verifying the metrics against the targets.",
                _call("think", thought="Verifying both signals against targets."),
            ),
            _output(
                "Verification passed. Reporting the final numbers.",
                _call(
                    "submit",
                    answer=(
                        "Improvements applied. A=50 (was 42), B=12 (was 17), "
                        "C=91 unchanged."
                    ),
                ),
            ),
        ],
    )


def _parent_model() -> Model:
    return get_model(
        "mockllm/model",
        custom_outputs=[
            _output(
                "I'll record the goal in memory so subagents have shared "
                "context to refer back to.",
                _call(
                    "memory",
                    command="create",
                    path="/memories/context.md",
                    file_text="Goal: investigate baseline, plan improvements, execute.",
                ),
            ),
            _output(
                "Now I'll lay out a three-step plan so progress is tracked as "
                "each step lands.",
                _call(
                    "todo_write",
                    todos=[
                        {
                            "content": "Gather baseline metrics",
                            "status": "in_progress",
                        },
                        {"content": "Plan improvements", "status": "pending"},
                        {"content": "Execute improvements", "status": "pending"},
                    ],
                ),
            ),
            _output(
                "Dispatching the research subagent to gather baseline metrics "
                "for signals A, B, and C.",
                _call(
                    "agent",
                    subagent_type="research",
                    prompt="Gather baseline metrics for signals A, B, and C.",
                    task_description="Baseline metrics",
                ),
            ),
            _output(
                "Research is back: A and B are below target. Updating the plan "
                "before dispatching the planner.",
                _call(
                    "todo_write",
                    todos=[
                        {
                            "content": "Gather baseline metrics",
                            "status": "completed",
                        },
                        {
                            "content": "Plan improvements",
                            "status": "in_progress",
                        },
                        {"content": "Execute improvements", "status": "pending"},
                    ],
                ),
            ),
            _output(
                "Dispatching the planning subagent to recommend targeted fixes "
                "for A and B.",
                _call(
                    "agent",
                    subagent_type="plan",
                    prompt=(
                        "Given baseline A=42, B=17, C=91, plan targeted "
                        "improvements. A and B are below target."
                    ),
                    task_description="Plan improvements",
                ),
            ),
            _output(
                "Plan in hand. Dispatching the general subagent to execute the "
                "recommended changes.",
                _call(
                    "agent",
                    subagent_type="general",
                    prompt=(
                        "Execute the plan: tune A's threshold and compress B's payload."
                    ),
                    task_description="Execute improvements",
                ),
            ),
            _output(
                "All three steps are done. Summarizing the outcome and submitting.",
                _call(
                    "submit",
                    answer=(
                        "Investigated baselines, planned improvements, and "
                        "executed: A=50, B=12, C=91. All targets met."
                    ),
                ),
            ),
        ],
    )


@task
def deepagent_demo() -> Task:
    research_sa = research(model=_research_model(), tools=[think()])
    plan_sa = plan(model=_plan_model(), tools=[think()])
    general_sa = general(model=_general_model(), tools=[think()])

    agent = deepagent(
        model=_parent_model(),
        subagents=[research_sa, plan_sa, general_sa],
        submit=True,
    )

    return Task(
        dataset=[
            Sample(
                input=(
                    "Investigate signals A, B, and C; plan targeted improvements; "
                    "then execute them."
                )
            )
        ],
        solver=agent,
        message_limit=40,
    )
