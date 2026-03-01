"""Generate .eval log files covering key timeline code paths.

Run:
    python tests/timeline/generate.py

Produces .eval files in tests/timeline/logs/ that exercise:
  1. Simple agent     – single tool call + submit
  2. Multi-turn agent – multiple tool calls before submit
  3. Nested sub-agent – parent delegates to child via as_tool()
  4. Auto-branching   – repeated model input fingerprint triggers branch detection
  5. Utility agent    – single-turn sub-agent with different system prompt
  6. Sequential run   – multiple run() calls with inference in between
  7. Parallel collect  – three parallel sub-agents via collect()
  8. Handoff + as_tool – combining handoff() and as_tool() sub-agents
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

import anyio

from inspect_ai import Task, eval
from inspect_ai.agent import Agent, AgentState, agent, as_tool, handoff, react, run
from inspect_ai.agent._types import AgentPrompt
from inspect_ai.dataset import Sample
from inspect_ai.event import Timeline, timeline_build
from inspect_ai.event._timeline import TimelineSpan
from inspect_ai.log import EvalLog
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import includes
from inspect_ai.tool import tool
from inspect_ai.util import collect

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool
def addition():
    async def execute(x: int, y: int) -> str:
        """Add two numbers.

        Args:
            x: First number.
            y: Second number.

        Returns:
            The sum as a string.
        """
        return str(x + y)

    return execute


@tool
def string_reverse():
    async def execute(text: str) -> str:
        """Reverse a string.

        Args:
            text: The string to reverse.

        Returns:
            The reversed string.
        """
        return text[::-1]

    return execute


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------

MODEL = "mockllm/model"
DATASET = [Sample(input="What is 1 + 1?", target=["2", "2.0"])]


async def _sync_run(
    agent_instance: Agent,
    messages: list[Any],
    *,
    name: str | None = None,
) -> AgentState:
    """Wrap run() with a yield point so parallel agents start together.

    mockllm returns instantly, so without this the first agent launched by
    collect() completes entirely before the second starts.  A short sleep
    lets the event loop schedule all tasks before any proceeds.
    """
    await anyio.sleep(0.01)
    return await run(agent_instance, messages, name=name)


def scenario_simple_agent() -> tuple[str, Task, Any]:
    """Single tool call + submit."""
    outputs = [
        ModelOutput.for_tool_call(MODEL, "addition", {"x": 1, "y": 1}),
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
    ]
    model = get_model(MODEL, custom_outputs=outputs)
    task = Task(
        name="simple_agent",
        dataset=DATASET,
        solver=react(tools=[addition()]),
        scorer=includes(),
    )
    return "simple_agent", task, model


def scenario_multi_turn_agent() -> tuple[str, Task, Any]:
    """Multiple tool calls before submit."""
    outputs = [
        ModelOutput.for_tool_call(MODEL, "addition", {"x": 1, "y": 1}),
        ModelOutput.for_tool_call(MODEL, "addition", {"x": 2, "y": 3}),
        ModelOutput.for_tool_call(MODEL, "string_reverse", {"text": "hello"}),
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
    ]
    model = get_model(MODEL, custom_outputs=outputs)
    task = Task(
        name="multi_turn_agent",
        dataset=DATASET,
        solver=react(tools=[addition(), string_reverse()]),
        scorer=includes(),
    )
    return "multi_turn_agent", task, model


def scenario_nested_sub_agent() -> tuple[str, Task, Any]:
    """Parent agent hands off to child agent via as_tool().

    Uses react() as the sub-agent so it creates proper nested agent spans.
    The sub-agent has its own tool loop: calls addition, then submits.
    """
    sub_agent = react(
        name="calculator",
        tools=[addition()],
        prompt=AgentPrompt(instructions="You are a calculator. Compute the answer."),
    )
    calc_tool = as_tool(sub_agent, description="A calculator that can add numbers.")
    outputs = [
        # Parent calls the sub-agent tool
        ModelOutput.for_tool_call(MODEL, "calculator", {"input": "What is 1 + 1?"}),
        # Sub-agent calls addition
        ModelOutput.for_tool_call(MODEL, "addition", {"x": 1, "y": 1}),
        # Sub-agent submits
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
        # Parent submits
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
    ]
    model = get_model(MODEL, custom_outputs=outputs)
    task = Task(
        name="nested_sub_agent",
        dataset=DATASET,
        solver=react(tools=[calc_tool]),
        scorer=includes(),
    )
    return "nested_sub_agent", task, model


def scenario_auto_branching() -> tuple[str, Task, Any]:
    """Simulate a re-roll by producing two model calls with identical input.

    Uses a react() agent with an on_continue callback that returns an
    AgentState with rolled-back messages (removing the assistant reply).
    This causes the next generate call to see the same input, producing
    two ModelEvents with identical input fingerprints and triggering
    _detect_auto_branches.
    """
    continue_count = 0

    async def rollback_once(state: AgentState) -> bool | str | AgentState:
        """Roll back assistant message once to trigger auto-branch detection.

        On first text-only reply, removes the assistant message so the next
        generate sees the same input.
        """
        nonlocal continue_count
        continue_count += 1
        if continue_count == 1:
            # Remove the assistant message to restore original input
            return AgentState(messages=list(state.messages[:-1]))
        return True

    outputs = [
        # First call — text output, will become branched off
        ModelOutput.from_content(MODEL, "Let me think about this..."),
        # Second call — same input fingerprint, stays in main timeline
        ModelOutput.for_tool_call(MODEL, "addition", {"x": 1, "y": 1}),
        # After tool result, submit
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
    ]
    model = get_model(MODEL, custom_outputs=outputs)
    task = Task(
        name="auto_branching",
        dataset=DATASET,
        solver=react(
            tools=[addition()],
            on_continue=rollback_once,
        ),
        scorer=includes(),
    )
    return "auto_branching", task, model


def scenario_utility_agent() -> tuple[str, Task, Any]:
    """Sub-agent with different system prompt → classified as utility.

    A utility agent has: single turn + different system prompt from parent.
    Uses react() as the sub-agent with its own prompt.
    """
    sub_agent = react(
        name="lookup",
        tools=[addition()],
        prompt=AgentPrompt(
            instructions="You are a lookup tool. Return the answer directly."
        ),
    )
    lookup_tool = as_tool(sub_agent, description="Look up factual information.")
    outputs = [
        # Parent calls the sub-agent tool
        ModelOutput.for_tool_call(MODEL, "lookup", {"input": "What is 1 + 1?"}),
        # Sub-agent submits immediately (single turn → utility candidate)
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
        # Parent submits
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
    ]
    model = get_model(MODEL, custom_outputs=outputs)
    task = Task(
        name="utility_agent",
        dataset=DATASET,
        solver=react(
            prompt=AgentPrompt(instructions="You are a math assistant."),
            tools=[lookup_tool],
        ),
        scorer=includes(),
    )
    return "utility_agent", task, model


def scenario_sequential_run() -> tuple[str, Task, Any]:
    """Sequential sub-agent invocations via run().

    A custom agent calls run() twice with a react agent named 'explore',
    with its own inference in between.
    """
    explore_agent = react(
        name="explore",
        tools=[addition()],
        prompt=AgentPrompt(instructions="Explore the problem."),
    )

    @agent
    def researcher() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            await anyio.sleep(0.15)
            # First exploration
            result = await run(explore_agent, state.messages)
            # Own inference between runs (sleep to create visible gap)
            await anyio.sleep(0.15)
            from inspect_ai.model import get_model as _get_model

            model = _get_model()
            state.output = await model.generate(result.messages)
            state.messages = list(result.messages) + [state.output.choices[0].message]
            await anyio.sleep(0.15)
            # Second exploration
            result = await run(explore_agent, state.messages)
            state.messages = list(result.messages)
            return state

        return execute

    outputs = [
        # First explore run: tool call + submit
        ModelOutput.for_tool_call(MODEL, "addition", {"x": 1, "y": 1}),
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
        # Researcher's own inference
        ModelOutput.from_content(MODEL, "Let me explore further."),
        # Second explore run: tool call + submit
        ModelOutput.for_tool_call(MODEL, "addition", {"x": 3, "y": 4}),
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "7"}),
    ]
    model = get_model(MODEL, custom_outputs=outputs)
    task = Task(
        name="sequential_run",
        dataset=DATASET,
        solver=researcher(),
        scorer=includes(),
    )
    return "sequential_run", task, model


def scenario_parallel_collect() -> tuple[str, Task, Any]:
    """Parallel sub-agents via collect().

    A custom agent launches 3 react agents named 'dig' in parallel
    using collect().  Each dig agent gets its own mockllm instance so
    they start at the same time instead of waiting on a shared queue.
    """
    dig1 = react(
        name="dig",
        tools=[addition()],
        prompt=AgentPrompt(instructions="Dig into the problem."),
        model=get_model(
            MODEL,
            custom_outputs=[
                ModelOutput.for_tool_call(MODEL, "addition", {"x": 1, "y": 1}),
                ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
            ],
        ),
    )
    dig2 = react(
        name="dig",
        tools=[addition()],
        prompt=AgentPrompt(instructions="Dig into the problem."),
        model=get_model(
            MODEL,
            custom_outputs=[
                ModelOutput.for_tool_call(MODEL, "addition", {"x": 2, "y": 3}),
                ModelOutput.for_tool_call(MODEL, "submit", {"answer": "5"}),
            ],
        ),
    )
    dig3 = react(
        name="dig",
        tools=[addition()],
        prompt=AgentPrompt(instructions="Dig into the problem."),
        model=get_model(
            MODEL,
            custom_outputs=[
                ModelOutput.for_tool_call(MODEL, "addition", {"x": 4, "y": 5}),
                ModelOutput.for_tool_call(MODEL, "submit", {"answer": "9"}),
            ],
        ),
    )

    @agent
    def coordinator() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            # Run 3 dig agents in parallel (_sync_run yields so they
            # all start before any completes with instant mockllm)
            results = await collect(
                _sync_run(dig1, state.messages, name="dig"),
                _sync_run(dig2, state.messages, name="dig"),
                _sync_run(dig3, state.messages, name="dig"),
            )
            # Use the last result
            state.messages = list(results[-1].messages)
            return state

        return execute

    # Dummy model for eval (not called directly)
    model = get_model(MODEL, custom_outputs=[])
    task = Task(
        name="parallel_collect",
        dataset=DATASET,
        solver=coordinator(),
        scorer=includes(),
    )
    return "parallel_collect", task, model


def scenario_deep_nesting() -> tuple[str, Task, Any]:
    """3 levels of agent nesting: parent → analyst → calculator."""
    calculator_agent = react(
        name="calculator",
        tools=[addition()],
        prompt=AgentPrompt(instructions="You are a calculator."),
    )
    analyst_agent = react(
        name="analyst",
        tools=[as_tool(calculator_agent, description="A calculator.")],
        prompt=AgentPrompt(instructions="You are an analyst."),
    )
    analyst_tool = as_tool(analyst_agent, description="An analyst agent.")
    outputs = [
        # Parent calls analyst
        ModelOutput.for_tool_call(MODEL, "analyst", {"input": "What is 1 + 1?"}),
        # Analyst calls calculator
        ModelOutput.for_tool_call(MODEL, "calculator", {"input": "Compute 1 + 1"}),
        # Calculator calls addition
        ModelOutput.for_tool_call(MODEL, "addition", {"x": 1, "y": 1}),
        # Calculator submits
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
        # Analyst submits
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
        # Parent submits
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
    ]
    model = get_model(MODEL, custom_outputs=outputs)
    task = Task(
        name="deep_nesting",
        dataset=DATASET,
        solver=react(tools=[analyst_tool]),
        scorer=includes(),
    )
    return "deep_nesting", task, model


def scenario_multiple_rerolls() -> tuple[str, Task, Any]:
    """3 re-rolls at the same level (2 rollbacks producing 3 branches)."""
    continue_count = 0

    async def rollback_twice(state: AgentState) -> bool | str | AgentState:
        """Roll back assistant message on counts 1 and 2."""
        nonlocal continue_count
        continue_count += 1
        if continue_count in (1, 2):
            return AgentState(messages=list(state.messages[:-1]))
        return True

    outputs = [
        # Attempt 1 — text, becomes branch 1
        ModelOutput.from_content(MODEL, "Attempt 1..."),
        # Attempt 2 — text, becomes branch 2
        ModelOutput.from_content(MODEL, "Attempt 2..."),
        # Attempt 3 — tool call, stays in main timeline
        ModelOutput.for_tool_call(MODEL, "addition", {"x": 1, "y": 1}),
        # Submit
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
    ]
    model = get_model(MODEL, custom_outputs=outputs)
    task = Task(
        name="multiple_rerolls",
        dataset=DATASET,
        solver=react(
            tools=[addition()],
            on_continue=rollback_twice,
        ),
        scorer=includes(),
    )
    return "multiple_rerolls", task, model


def scenario_parallel_with_nesting() -> tuple[str, Task, Any]:
    """Parallel agents that each have sub-agents.

    collect() launches 2 worker agents, each of which uses as_tool to call
    a nested helper react agent.  Each worker gets its own mockllm instance
    so they start at the same time.
    """
    helper1 = react(
        name="helper",
        tools=[addition()],
        prompt=AgentPrompt(instructions="Help with calculations."),
        model=get_model(
            MODEL,
            custom_outputs=[
                ModelOutput.for_tool_call(MODEL, "addition", {"x": 1, "y": 1}),
                ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
            ],
        ),
    )
    helper2 = react(
        name="helper",
        tools=[addition()],
        prompt=AgentPrompt(instructions="Help with calculations."),
        model=get_model(
            MODEL,
            custom_outputs=[
                ModelOutput.for_tool_call(MODEL, "addition", {"x": 2, "y": 3}),
                ModelOutput.for_tool_call(MODEL, "submit", {"answer": "5"}),
            ],
        ),
    )

    @agent
    def worker1_fn() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            inner = react(
                name="worker_inner",
                tools=[
                    as_tool(helper1, description="A helper agent."),
                ],
                prompt=AgentPrompt(instructions="Do the work."),
                model=get_model(
                    MODEL,
                    custom_outputs=[
                        ModelOutput.for_tool_call(
                            MODEL, "helper", {"input": "compute 1+1"}
                        ),
                        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
                    ],
                ),
            )
            return await inner(state)

        return execute

    @agent
    def worker2_fn() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            inner = react(
                name="worker_inner",
                tools=[
                    as_tool(helper2, description="A helper agent."),
                ],
                prompt=AgentPrompt(instructions="Do the work."),
                model=get_model(
                    MODEL,
                    custom_outputs=[
                        ModelOutput.for_tool_call(
                            MODEL, "helper", {"input": "compute 2+3"}
                        ),
                        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "5"}),
                    ],
                ),
            )
            return await inner(state)

        return execute

    worker1_agent = worker1_fn()
    worker2_agent = worker2_fn()

    @agent
    def manager() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            results = await collect(
                _sync_run(worker1_agent, state.messages, name="worker"),
                _sync_run(worker2_agent, state.messages, name="worker"),
            )
            state.messages = list(results[-1].messages)
            return state

        return execute

    # Dummy model for eval (not called directly)
    model = get_model(MODEL, custom_outputs=[])
    task = Task(
        name="parallel_with_nesting",
        dataset=DATASET,
        solver=manager(),
        scorer=includes(),
    )
    return "parallel_with_nesting", task, model


def scenario_sequential_and_parallel() -> tuple[str, Task, Any]:
    """Sequential run → parallel collect → sequential run.

    A custom agent does: run(scout) → collect(run(dig), run(dig)) → run(scout).
    The two dig agents get separate mockllm instances so they start at the
    same time.  The scouts are sequential and share the eval-level model.
    """
    scout_agent = react(
        name="scout",
        tools=[addition()],
        prompt=AgentPrompt(instructions="Scout the area."),
    )
    dig1 = react(
        name="dig",
        tools=[addition()],
        prompt=AgentPrompt(instructions="Dig into the problem."),
        model=get_model(
            MODEL,
            custom_outputs=[
                ModelOutput.for_tool_call(MODEL, "addition", {"x": 2, "y": 3}),
                ModelOutput.for_tool_call(MODEL, "submit", {"answer": "5"}),
            ],
        ),
    )
    dig2 = react(
        name="dig",
        tools=[addition()],
        prompt=AgentPrompt(instructions="Dig into the problem."),
        model=get_model(
            MODEL,
            custom_outputs=[
                ModelOutput.for_tool_call(MODEL, "addition", {"x": 4, "y": 5}),
                ModelOutput.for_tool_call(MODEL, "submit", {"answer": "9"}),
            ],
        ),
    )

    @agent
    def expedition() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            # Sequential: first scout
            result = await run(scout_agent, state.messages)
            # Parallel: two diggers
            dig_results = await collect(
                _sync_run(dig1, result.messages, name="dig"),
                _sync_run(dig2, result.messages, name="dig"),
            )
            # Sequential: second scout
            result = await run(scout_agent, dig_results[-1].messages)
            state.messages = list(result.messages)
            return state

        return execute

    # Eval-level model handles sequential scouts only
    outputs = [
        # Scout 1: addition + submit
        ModelOutput.for_tool_call(MODEL, "addition", {"x": 1, "y": 1}),
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
        # Scout 2: addition + submit
        ModelOutput.for_tool_call(MODEL, "addition", {"x": 6, "y": 7}),
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "13"}),
    ]
    model = get_model(MODEL, custom_outputs=outputs)
    task = Task(
        name="sequential_and_parallel",
        dataset=DATASET,
        solver=expedition(),
        scorer=includes(),
    )
    return "sequential_and_parallel", task, model


def scenario_deep_utility() -> tuple[str, Task, Any]:
    """Utility detection across nesting levels.

    Parent react (prompt A) → dispatcher (prompt B, multi-turn so NOT utility)
    → lookup (prompt C, single-turn so IS utility).
    """
    lookup_agent = react(
        name="lookup",
        tools=[addition()],
        prompt=AgentPrompt(instructions="You are a lookup tool. Return directly."),
    )
    dispatcher_agent = react(
        name="dispatcher",
        tools=[
            addition(),
            as_tool(lookup_agent, description="Look up information."),
        ],
        prompt=AgentPrompt(instructions="You are a dispatcher."),
    )
    dispatcher_tool = as_tool(dispatcher_agent, description="Dispatch to sub-agents.")
    outputs = [
        # Parent calls dispatcher
        ModelOutput.for_tool_call(MODEL, "dispatcher", {"input": "dispatch this"}),
        # Dispatcher calls addition (makes it multi-turn → NOT utility)
        ModelOutput.for_tool_call(MODEL, "addition", {"x": 1, "y": 1}),
        # Dispatcher calls lookup
        ModelOutput.for_tool_call(MODEL, "lookup", {"input": "look up the answer"}),
        # Lookup submits immediately (single turn → utility)
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
        # Dispatcher submits
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
        # Parent submits
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
    ]
    model = get_model(MODEL, custom_outputs=outputs)
    task = Task(
        name="deep_utility",
        dataset=DATASET,
        solver=react(
            prompt=AgentPrompt(instructions="You are a math assistant."),
            tools=[dispatcher_tool],
        ),
        scorer=includes(),
    )
    return "deep_utility", task, model


def scenario_parallel_heterogeneous() -> tuple[str, Task, Any]:
    """Parallel agents with different names.

    collect() launches 3 agents: 'search', 'analyze', 'summarize'.
    Different names should result in separate repr rows, not grouped.
    Each agent gets its own mockllm instance so they start at the same time.
    """
    search_agent = react(
        name="search",
        tools=[addition()],
        prompt=AgentPrompt(instructions="Search for information."),
        model=get_model(
            MODEL,
            custom_outputs=[
                ModelOutput.for_tool_call(MODEL, "addition", {"x": 1, "y": 1}),
                ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
            ],
        ),
    )
    analyze_agent = react(
        name="analyze",
        tools=[string_reverse()],
        prompt=AgentPrompt(instructions="Analyze the data."),
        model=get_model(
            MODEL,
            custom_outputs=[
                ModelOutput.for_tool_call(MODEL, "string_reverse", {"text": "hello"}),
                ModelOutput.for_tool_call(MODEL, "submit", {"answer": "olleh"}),
            ],
        ),
    )
    summarize_agent = react(
        name="summarize",
        tools=[addition()],
        prompt=AgentPrompt(instructions="Summarize the findings."),
        model=get_model(
            MODEL,
            custom_outputs=[
                ModelOutput.for_tool_call(MODEL, "addition", {"x": 2, "y": 3}),
                ModelOutput.for_tool_call(MODEL, "submit", {"answer": "5"}),
            ],
        ),
    )

    @agent
    def orchestrator() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            results = await collect(
                _sync_run(search_agent, state.messages, name="search"),
                _sync_run(analyze_agent, state.messages, name="analyze"),
                _sync_run(summarize_agent, state.messages, name="summarize"),
            )
            state.messages = list(results[-1].messages)
            return state

        return execute

    # Dummy model for eval (not called directly)
    model = get_model(MODEL, custom_outputs=[])
    task = Task(
        name="parallel_heterogeneous",
        dataset=DATASET,
        solver=orchestrator(),
        scorer=includes(),
    )
    return "parallel_heterogeneous", task, model


def scenario_handoff_and_as_tool() -> tuple[str, Task, Any]:
    """Agent using both handoff() and as_tool() for sub-agents.

    A react agent has two sub-agents available:
      - 'analyst' via handoff() (model transfers control)
      - 'calculator' via as_tool() (model calls as tool)

    Custom @agent functions with an `input` parameter are used so that
    handoff() and as_tool() expose it as a tool parameter.
    """

    @agent
    def analyst() -> Agent:
        """Analyze the input by reversing strings."""

        async def execute(state: AgentState, input: str = "") -> AgentState:
            """Run the analyst agent.

            Args:
                state: The agent state.
                input: The input to analyze.
            """
            inner = react(
                name="analyst_inner",
                tools=[string_reverse()],
                prompt=AgentPrompt(instructions="Analyze the input."),
            )
            return await inner(state)

        return execute

    @agent
    def calculator() -> Agent:
        """Compute numerical answers."""

        async def execute(state: AgentState, input: str = "") -> AgentState:
            """Run the calculator agent.

            Args:
                state: The agent state.
                input: The calculation to perform.
            """
            inner = react(
                name="calculator_inner",
                tools=[addition()],
                prompt=AgentPrompt(instructions="Compute the answer."),
            )
            return await inner(state)

        return execute

    analyst_handoff = handoff(analyst(), description="Transfer to analyst.")
    calc_tool = as_tool(calculator(), description="A calculator.")

    outputs = [
        # Parent hands off to analyst
        ModelOutput.for_tool_call(
            MODEL, "transfer_to_analyst", {"input": "analyze this"}
        ),
        # Analyst inner react: reverse + submit
        ModelOutput.for_tool_call(MODEL, "string_reverse", {"text": "hello"}),
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "olleh"}),
        # Parent calls calculator as tool
        ModelOutput.for_tool_call(MODEL, "calculator", {"input": "What is 1 + 1?"}),
        # Calculator inner react: addition + submit
        ModelOutput.for_tool_call(MODEL, "addition", {"x": 1, "y": 1}),
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
        # Parent submits
        ModelOutput.for_tool_call(MODEL, "submit", {"answer": "2"}),
    ]
    model = get_model(MODEL, custom_outputs=outputs)
    task = Task(
        name="handoff_and_as_tool",
        dataset=DATASET,
        solver=react(tools=[analyst_handoff, calc_tool]),
        scorer=includes(),
    )
    return "handoff_and_as_tool", task, model


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def child_span_names(span: TimelineSpan) -> list[str]:
    """Get names of direct child spans."""
    return [item.name for item in span.content if isinstance(item, TimelineSpan)]


def find_spans(span: TimelineSpan, name: str) -> list[TimelineSpan]:
    """Find all descendant spans with a given name (case-insensitive)."""
    results: list[TimelineSpan] = []
    target = name.lower()
    for item in span.content:
        if isinstance(item, TimelineSpan):
            if item.name == target:
                results.append(item)
            results.extend(find_spans(item, name))
    return results


def assert_repr_labels(timeline: Timeline, *labels: str) -> None:
    """Assert that repr output contains lines with these labels."""
    text = repr(timeline)
    for label in labels:
        assert label in text, f"Expected label {label!r} in repr output:\n{text}"


def assert_repr_not_contains(timeline: Timeline, *labels: str) -> None:
    """Assert that repr output does NOT contain these labels."""
    text = repr(timeline)
    for label in labels:
        assert label not in text, (
            f"Label {label!r} should NOT appear in repr output:\n{text}"
        )


# ---------------------------------------------------------------------------
# Per-scenario validators
# ---------------------------------------------------------------------------


def validate_simple_agent(timeline: Timeline) -> None:
    root = timeline.root
    children = child_span_names(root)
    assert "react" in children, f"Expected 'react' in root children: {children}"
    react_spans = find_spans(root, "react")
    assert len(react_spans) == 1
    # react has no agent sub-spans
    react_children = [
        s for s in child_span_names(react_spans[0]) if s not in ("init", "scoring")
    ]
    assert react_children == [], (
        f"react should have no agent sub-spans: {react_children}"
    )
    assert_repr_labels(timeline, "main", "react")


def validate_multi_turn_agent(timeline: Timeline) -> None:
    root = timeline.root
    children = child_span_names(root)
    assert "react" in children, f"Expected 'react' in root children: {children}"
    react_spans = find_spans(root, "react")
    assert len(react_spans) == 1
    assert_repr_labels(timeline, "main", "react")


def validate_nested_sub_agent(timeline: Timeline) -> None:
    root = timeline.root
    calc_spans = find_spans(root, "calculator")
    assert len(calc_spans) >= 1, "Expected at least one 'calculator' span"
    # At least one calculator span should be an agent type
    agent_calcs = [s for s in calc_spans if s.span_type == "agent"]
    assert len(agent_calcs) >= 1, "Expected calculator span with span_type='agent'"
    assert_repr_labels(timeline, "main", "react", "calculator")


def validate_auto_branching(timeline: Timeline) -> None:
    root = timeline.root
    react_spans = find_spans(root, "react")
    assert len(react_spans) >= 1, "Expected 'react' span"
    react_span = react_spans[0]
    assert len(react_span.branches) >= 1, (
        f"Expected at least 1 branch on react, got {len(react_span.branches)}"
    )
    text = repr(timeline)
    assert "\u21b3" in text, "Expected branch marker '\u21b3' in repr"
    assert_repr_labels(timeline, "main", "react")


def validate_utility_agent(timeline: Timeline) -> None:
    root = timeline.root
    # The inner lookup span should have utility=True
    lookup_spans = find_spans(root, "lookup")
    assert len(lookup_spans) >= 1, "Expected at least one 'lookup' span"
    utility_lookups = [s for s in lookup_spans if s.utility]
    assert len(utility_lookups) >= 1, (
        "Expected at least one lookup span with utility=True"
    )
    assert_repr_labels(timeline, "main", "react", "lookup")


def validate_sequential_run(timeline: Timeline) -> None:
    root = timeline.root
    children = child_span_names(root)
    assert "researcher" in children, (
        f"Expected 'researcher' in root children: {children}"
    )
    explore_spans = find_spans(root, "explore")
    assert len(explore_spans) >= 1, "Expected at least one 'explore' span"
    assert_repr_labels(timeline, "main", "researcher", "explore")


def validate_parallel_collect(timeline: Timeline) -> None:
    root = timeline.root
    children = child_span_names(root)
    assert "coordinator" in children, (
        f"Expected 'coordinator' in root children: {children}"
    )
    dig_spans = find_spans(root, "dig")
    assert len(dig_spans) >= 3, f"Expected at least 3 'dig' spans, got {len(dig_spans)}"
    text = repr(timeline)
    assert "dig" in text, "Expected 'dig' label in repr"
    assert "\u2462" in text, "Expected '\u2462' (circled 3) marker in repr"


def validate_handoff_and_as_tool(timeline: Timeline) -> None:
    root = timeline.root
    react_spans = find_spans(root, "react")
    assert len(react_spans) >= 1, "Expected 'react' span"
    # Both sub-agents should exist somewhere in the tree
    analyst_spans = find_spans(root, "transfer_to_analyst")
    calc_spans = find_spans(root, "calculator")
    assert len(analyst_spans) >= 1, "Expected 'transfer_to_analyst' span"
    assert len(calc_spans) >= 1, "Expected 'calculator' span"
    # Both should be agent type
    assert any(s.span_type == "agent" for s in analyst_spans), (
        "Expected transfer_to_analyst with span_type='agent'"
    )
    assert any(s.span_type == "agent" for s in calc_spans), (
        "Expected calculator with span_type='agent'"
    )
    assert_repr_labels(timeline, "main", "react", "transfer_to_analyst", "calculator")


def validate_deep_nesting(timeline: Timeline) -> None:
    root = timeline.root
    analyst_spans = find_spans(root, "analyst")
    assert len(analyst_spans) >= 1, "Expected at least one 'analyst' span"
    assert any(s.span_type == "agent" for s in analyst_spans), (
        "Expected analyst span with span_type='agent'"
    )
    calc_spans = find_spans(root, "calculator")
    assert len(calc_spans) >= 1, "Expected at least one 'calculator' span"
    assert any(s.span_type == "agent" for s in calc_spans), (
        "Expected calculator span with span_type='agent'"
    )
    # Calculator should be nested inside analyst
    for a_span in analyst_spans:
        nested_calcs = find_spans(a_span, "calculator")
        if nested_calcs:
            break
    else:
        raise AssertionError("Expected calculator nested inside analyst")
    assert_repr_labels(timeline, "analyst")


def validate_multiple_rerolls(timeline: Timeline) -> None:
    root = timeline.root
    react_spans = find_spans(root, "react")
    assert len(react_spans) >= 1, "Expected 'react' span"
    react_span = react_spans[0]
    assert len(react_span.branches) >= 2, (
        f"Expected at least 2 branches on react, got {len(react_span.branches)}"
    )
    text = repr(timeline)
    assert "\u21b3" in text, "Expected branch marker '\u21b3' in repr"


def validate_parallel_with_nesting(timeline: Timeline) -> None:
    root = timeline.root
    worker_spans = find_spans(root, "worker")
    assert len(worker_spans) >= 2, (
        f"Expected at least 2 'worker' spans, got {len(worker_spans)}"
    )
    helper_spans = find_spans(root, "helper")
    assert len(helper_spans) >= 2, (
        f"Expected at least 2 'helper' spans, got {len(helper_spans)}"
    )
    # Helpers should be nested inside workers
    for w_span in worker_spans:
        nested_helpers = find_spans(w_span, "helper")
        if nested_helpers:
            break
    else:
        raise AssertionError("Expected helper nested inside worker")
    text = repr(timeline)
    assert "\u2461" in text, "Expected '\u2461' (circled 2) marker in repr"


def validate_sequential_and_parallel(timeline: Timeline) -> None:
    root = timeline.root
    scout_spans = find_spans(root, "scout")
    assert len(scout_spans) >= 2, (
        f"Expected at least 2 'scout' spans, got {len(scout_spans)}"
    )
    dig_spans = find_spans(root, "dig")
    assert len(dig_spans) >= 2, f"Expected at least 2 'dig' spans, got {len(dig_spans)}"
    text = repr(timeline)
    assert "scout" in text, "Expected 'scout' label in repr"
    assert "dig" in text, "Expected 'dig' label in repr"


def validate_deep_utility(timeline: Timeline) -> None:
    root = timeline.root
    dispatcher_spans = find_spans(root, "dispatcher")
    assert len(dispatcher_spans) >= 1, "Expected at least one 'dispatcher' span"
    assert any(not s.utility for s in dispatcher_spans), (
        "Expected dispatcher span with utility=False"
    )
    lookup_spans = find_spans(root, "lookup")
    assert len(lookup_spans) >= 1, "Expected at least one 'lookup' span"
    assert any(s.utility for s in lookup_spans), (
        "Expected lookup span with utility=True"
    )
    assert_repr_labels(timeline, "dispatcher", "lookup")


def validate_parallel_heterogeneous(timeline: Timeline) -> None:
    root = timeline.root
    search_spans = find_spans(root, "search")
    assert len(search_spans) >= 1, "Expected at least one 'search' span"
    analyze_spans = find_spans(root, "analyze")
    assert len(analyze_spans) >= 1, "Expected at least one 'analyze' span"
    summarize_spans = find_spans(root, "summarize")
    assert len(summarize_spans) >= 1, "Expected at least one 'summarize' span"
    text = repr(timeline)
    assert "search" in text, "Expected 'search' in repr"
    assert "analyze" in text, "Expected 'analyze' in repr"
    assert "summarize" in text, "Expected 'summarize' in repr"
    # Different names should not be grouped with count markers
    assert "\u2461" not in text, "Expected no '\u2461' marker (different names)"
    assert "\u2462" not in text, "Expected no '\u2462' marker (different names)"


VALIDATORS: dict[str, Any] = {
    "simple_agent": validate_simple_agent,
    "multi_turn_agent": validate_multi_turn_agent,
    "nested_sub_agent": validate_nested_sub_agent,
    "auto_branching": validate_auto_branching,
    "utility_agent": validate_utility_agent,
    "sequential_run": validate_sequential_run,
    "parallel_collect": validate_parallel_collect,
    "handoff_and_as_tool": validate_handoff_and_as_tool,
    "deep_nesting": validate_deep_nesting,
    "multiple_rerolls": validate_multiple_rerolls,
    "parallel_with_nesting": validate_parallel_with_nesting,
    "sequential_and_parallel": validate_sequential_and_parallel,
    "deep_utility": validate_deep_utility,
    "parallel_heterogeneous": validate_parallel_heterogeneous,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

SCENARIOS = [
    scenario_simple_agent,
    scenario_multi_turn_agent,
    scenario_nested_sub_agent,
    scenario_auto_branching,
    scenario_utility_agent,
    scenario_sequential_run,
    scenario_parallel_collect,
    scenario_handoff_and_as_tool,
    scenario_deep_nesting,
    scenario_multiple_rerolls,
    scenario_parallel_with_nesting,
    scenario_sequential_and_parallel,
    scenario_deep_utility,
    scenario_parallel_heterogeneous,
]


def main() -> None:
    log_dir = Path(__file__).parent / "logs"

    # Remove and recreate logs directory
    if log_dir.exists():
        shutil.rmtree(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / ".gitignore").write_text("*\n!.gitignore\n")

    print(f"Generating timeline test data in {log_dir}/\n")

    results: list[tuple[str, str, EvalLog]] = []

    for scenario_fn in SCENARIOS:
        name, task, model = scenario_fn()
        print(f"  Running: {name}...")
        logs = eval(
            task,
            model=model,
            log_dir=str(log_dir),
            display="none",
        )
        log = logs[0]
        if log.status != "success":
            print(f"    WARNING: {name} finished with status={log.status}")
            if log.error:
                print(f"    Error: {log.error.message}")
        results.append((name, log.location or "", log))

    # Validate and print timeline repr for each scenario
    print()
    failures: list[str] = []
    for name, _location, log in results:
        assert log.status == "success", (
            f"{name}: expected status='success', got '{log.status}'"
            + (f" ({log.error.message})" if log.error else "")
        )

        if not log.samples or not log.samples[0].events:
            print(f"--- {name}: (no events) ---\n")
            continue

        events = log.samples[0].events
        timeline = timeline_build(events)
        print(f"--- {name} ---")
        print(repr(timeline))
        print()

        # Run structural + repr validation
        validator = VALIDATORS.get(name)
        if validator:
            try:
                validator(timeline)
                print(f"  [PASS] {name}\n")
            except AssertionError as e:
                print(f"  [FAIL] {name}: {e}\n")
                failures.append(f"{name}: {e}")
        else:
            print(f"  [SKIP] {name}: no validator\n")

    if failures:
        print(f"\n{len(failures)} scenario(s) failed validation:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All scenarios passed validation.")


if __name__ == "__main__":
    main()
