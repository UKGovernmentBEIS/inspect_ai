"""End-to-end demo scenarios for deepagent(), exercised as tests.

These were previously standalone files under examples/. They run a full
deepagent trajectory through eval() with per-agent mockllm instances:

- ``test_deepagent_demo`` — synchronous subagent delegation (research → plan →
  execute) plus memory and todo_write.
- ``test_deepagent_background_demo`` — background dispatch: three subagents fanned
  out concurrently, inspected via the lifecycle tools (agent_list / agent_status),
  one cancelled (agent_cancel), the rest collected (agent_wait). Marked ``slow``
  because it uses real ``anyio.sleep`` so the background runs genuinely overlap.

Assertions are timing-independent: they rely on the deterministic outcomes
(cancellation of a long-running agent, agent_wait blocking until completion),
not on wall-clock races.
"""

from __future__ import annotations

import uuid
from typing import Any

import anyio
import pytest

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentText
from inspect_ai.agent import deepagent, general, plan, research, subagent
from inspect_ai.dataset import Sample
from inspect_ai.event._tool import ToolEvent
from inspect_ai.model import Model, ModelOutput, get_model
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._model_output import ChatCompletionChoice
from inspect_ai.tool import Tool, ToolCall, think, tool


def _output(narration: str, *tool_calls: ToolCall) -> ModelOutput:
    """A ModelOutput with rich ContentText narration + zero-or-more tool calls.

    The typed ``[ContentText(...)]`` content list matches what a real model
    emits and exercises the assistant-message-with-content serialization path.
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
        id=f"call_{uuid.uuid4().hex[:8]}", function=name, arguments=arguments
    )


def _tool_events(log: Any, function: str) -> list[ToolEvent]:
    sample = log.samples[0]
    return [
        e for e in sample.events if isinstance(e, ToolEvent) and e.function == function
    ]


def _span_names(log: Any) -> list[str | None]:
    return [
        getattr(e, "name", None)
        for e in log.samples[0].events
        if e.event == "span_begin"
    ]


# ===========================================================================
# Synchronous delegation demo
# ===========================================================================


def _research_model() -> Model:
    return get_model(
        "mockllm/model",
        custom_outputs=[
            _output(
                "Starting with the three signals.",
                _call("think", thought="Need baseline metrics for A, B, and C."),
            ),
            _output(
                "Cross-referencing against historical norms.",
                _call("think", thought="Comparing to last quarter's targets."),
            ),
            _output(
                "Numbers validated. Reporting back.",
                _call(
                    "submit",
                    answer="Baseline — A=42, B=17, C=91. A and B are below target.",
                ),
            ),
        ],
    )


def _plan_model() -> Model:
    return get_model(
        "mockllm/model",
        custom_outputs=[
            _output(
                "Two signals need work; weighing cost vs impact.",
                _call("think", thought="A and B need work."),
            ),
            _output(
                "Plan ready.",
                _call(
                    "submit",
                    answer="Plan: tune A's threshold, compress B's payload, leave C.",
                ),
            ),
        ],
    )


def _general_model() -> Model:
    return get_model(
        "mockllm/model",
        custom_outputs=[
            _output(
                "Tuning A per the plan.",
                _call("think", thought="Tuning A's threshold first."),
            ),
            _output(
                "Verifying both signals against targets.",
                _call("think", thought="Verifying."),
            ),
            _output(
                "Verification passed.",
                _call(
                    "submit",
                    answer="Applied. A=50 (was 42), B=12 (was 17), C=91 unchanged.",
                ),
            ),
        ],
    )


def _sync_parent_model() -> Model:
    return get_model(
        "mockllm/model",
        custom_outputs=[
            _output(
                "Recording the goal in memory.",
                _call(
                    "memory",
                    command="create",
                    path="/memories/context.md",
                    file_text="Goal: investigate, plan, execute.",
                ),
            ),
            _output(
                "Laying out a three-step plan.",
                _call(
                    "todo_write",
                    todos=[
                        {"content": "Gather baseline metrics", "status": "in_progress"},
                        {"content": "Plan improvements", "status": "pending"},
                        {"content": "Execute improvements", "status": "pending"},
                    ],
                ),
            ),
            _output(
                "Dispatching research to gather baseline metrics.",
                _call(
                    "agent",
                    subagent_type="research",
                    prompt="Gather baseline metrics for signals A, B, and C.",
                    task_description="Baseline metrics",
                ),
            ),
            _output(
                "Research is back. Dispatching the planner.",
                _call(
                    "agent",
                    subagent_type="plan",
                    prompt="Given baseline A=42, B=17, C=91, plan improvements.",
                    task_description="Plan improvements",
                ),
            ),
            _output(
                "Plan in hand. Dispatching general to execute.",
                _call(
                    "agent",
                    subagent_type="general",
                    prompt="Execute the plan: tune A and compress B.",
                    task_description="Execute improvements",
                ),
            ),
            _output(
                "All three steps done. Submitting.",
                _call(
                    "submit",
                    answer="Investigated, planned, executed: A=50, B=12, C=91.",
                ),
            ),
        ],
    )


def test_deepagent_demo() -> None:
    agent = deepagent(
        model=_sync_parent_model(),
        subagents=[
            research(model=_research_model(), tools=[think()]),
            plan(model=_plan_model(), tools=[think()]),
            general(model=_general_model(), tools=[think()]),
        ],
        submit=True,
    )
    task = Task(
        dataset=[Sample(input="Investigate A, B, C; plan improvements; execute.")],
        solver=agent,
        message_limit=40,
    )
    log = eval(task, model="mockllm/model")[0]

    assert log.status == "success"
    # all three subagents were dispatched and ran
    assert len(_tool_events(log, "agent")) == 3
    span_names = _span_names(log)
    for name in ("research", "plan", "general"):
        assert name in span_names
    # memory + planning tools were used
    assert len(_tool_events(log, "memory")) == 1
    assert len(_tool_events(log, "todo_write")) == 1
    # final answer present
    assert log.samples is not None
    answer = log.samples[0].output.completion
    assert "A=50" in answer


# ===========================================================================
# Background dispatch demo (slow — uses real anyio.sleep)
# ===========================================================================


@tool
def slow_work() -> Tool:
    """Work that takes real time, so background runs genuinely overlap."""

    async def execute(step: str, seconds: float = 1.0) -> str:
        """Simulate a slow unit of work.

        Args:
            step: Short description of the work.
            seconds: How long the work takes (wall-clock seconds).
        """
        await anyio.sleep(seconds)
        return f"Completed: {step}"

    return execute


def _alpha_model() -> Model:
    return get_model(
        "mockllm/model",
        custom_outputs=[
            _output(
                "Pulling Alpha's pricing.",
                _call("slow_work", step="scrape Alpha pricing", seconds=1.0),
            ),
            _output(
                "Alpha picture is clear.",
                _call("submit", answer="Alpha: premium, enterprise-strong, weak SMB."),
            ),
        ],
    )


def _beta_model() -> Model:
    return get_model(
        "mockllm/model",
        custom_outputs=[
            _output(
                "Gathering Beta's pricing.",
                _call("slow_work", step="scrape Beta pricing", seconds=1.0),
            ),
            _output(
                "Beta synthesis done.",
                _call("submit", answer="Beta: aggressive mid-market, weak enterprise."),
            ),
        ],
    )


def _gamma_model() -> Model:
    # Long-running and cancelled mid-flight — never reaches submit.
    return get_model(
        "mockllm/model",
        custom_outputs=[
            _output(
                "Starting the slow Gamma teardown.",
                _call("slow_work", step="full Gamma teardown", seconds=8.0),
            ),
            _output("Should not reach here.", _call("submit", answer="(unreached)")),
        ],
    )


def _research_subagent(name: str, competitor: str, model: Model):
    return subagent(
        name=name,
        description=f"Researches competitor {competitor}.",
        prompt=f"Research competitor {competitor}, then submit a findings summary.",
        model=model,
        tools=[slow_work(), think()],
    )


def _bg_parent_model() -> Model:
    return get_model(
        "mockllm/model",
        custom_outputs=[
            _output(
                "Laying out the plan.",
                _call(
                    "todo_write",
                    todos=[
                        {"content": "Research Alpha", "status": "in_progress"},
                        {"content": "Research Beta", "status": "in_progress"},
                        {"content": "Research Gamma", "status": "in_progress"},
                    ],
                ),
            ),
            _output(
                "Kicking off Alpha in the background.",
                _call(
                    "agent",
                    subagent_type="research_alpha",
                    prompt="Research Alpha.",
                    task_description="Research Alpha",
                    background=True,
                ),
            ),
            _output(
                "Beta in the background.",
                _call(
                    "agent",
                    subagent_type="research_beta",
                    prompt="Research Beta.",
                    task_description="Research Beta",
                    background=True,
                ),
            ),
            _output(
                "Gamma in the background.",
                _call(
                    "agent",
                    subagent_type="research_gamma",
                    prompt="Research Gamma.",
                    task_description="Research Gamma",
                    background=True,
                ),
            ),
            _output(
                "Drafting the outline while they run.",
                _call("slow_work", step="draft outline", seconds=0.5),
            ),
            _output("Checking what's in flight.", _call("agent_list")),
            _output("Peeking at Alpha.", _call("agent_status", agent_id="AGENT-1")),
            _output(
                "Gamma is out of scope — cancelling it.",
                _call("agent_cancel", agent_id="AGENT-3"),
            ),
            _output(
                "Waiting for Alpha and Beta.",
                _call("agent_wait", agent_ids=["AGENT-1", "AGENT-2"], mode="all"),
            ),
            _output(
                "Both in. Submitting.",
                _call("submit", answer="Competitive analysis complete (Gamma cut)."),
            ),
        ],
    )


@pytest.mark.slow
def test_deepagent_background_demo() -> None:
    agent = deepagent(
        model=_bg_parent_model(),
        subagents=[
            _research_subagent("research_alpha", "Alpha", _alpha_model()),
            _research_subagent("research_beta", "Beta", _beta_model()),
            _research_subagent("research_gamma", "Gamma", _gamma_model()),
        ],
        tools=[think(), slow_work()],
        background=True,
        submit=True,
    )
    task = Task(
        dataset=[Sample(input="Competitive analysis of Alpha, Beta, Gamma.")],
        solver=agent,
        message_limit=80,
    )
    log = eval(task, model="mockllm/model")[0]

    assert log.status == "success"

    # all three background subagents were dispatched and have spans
    assert len(_tool_events(log, "agent")) == 3
    span_names = _span_names(log)
    for name in ("research_alpha", "research_beta", "research_gamma"):
        assert name in span_names

    # all four lifecycle tools were exercised
    for fn in ("agent_list", "agent_status", "agent_cancel", "agent_wait"):
        assert len(_tool_events(log, fn)) == 1

    # Gamma (the long-running one) was cancelled deterministically — the parent
    # cancels it ~0.5s in while it sleeps 8s.
    cancel_body = str(_tool_events(log, "agent_cancel")[0].result)
    assert "AGENT-3" in cancel_body and "cancelled" in cancel_body

    # agent_wait(all) blocks until Alpha and Beta complete, so their results are
    # deterministically present.
    wait_body = str(_tool_events(log, "agent_wait")[0].result)
    assert "AGENT-1" in wait_body and "completed" in wait_body
    assert "Alpha:" in wait_body and "Beta:" in wait_body
