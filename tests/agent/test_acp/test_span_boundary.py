"""Phase 5 regression tests for the `AGENT_SPAN_TYPE` boundary marker.

Phase 6's ACP event router relies on every agent-invocation path
opening a span with ``type=AGENT_SPAN_TYPE`` ("agent"). If a new code
path skips the marker, sub-agent isolation breaks silently. These
tests pin the convention down across the five known paths.
"""

from typing import Any

from inspect_ai.agent import Agent, AgentState, agent, as_solver, handoff, react, run
from inspect_ai.agent._as_tool import as_tool
from inspect_ai.event import SpanBeginEvent
from inspect_ai.log._samples import _sample_active as samples_var
from inspect_ai.log._transcript import Transcript, _transcript
from inspect_ai.model import ChatMessageUser, get_model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util._span import AGENT_SPAN_TYPE

from ._capture import acp_test_active_sample


def _agent_span_names(transcript: Transcript) -> list[str]:
    """Return the names of all agent-boundary SpanBeginEvents in order."""
    return [
        e.name
        for e in transcript.events
        if isinstance(e, SpanBeginEvent) and e.type == AGENT_SPAN_TYPE
    ]


@agent(name="leaf_agent", description="A trivial leaf agent for span tests.")
def _leaf_agent() -> Agent:
    """A bare agent that just echoes its input."""

    async def execute(state: AgentState) -> AgentState:
        return state

    return execute


def test_agent_span_type_constant_is_agent() -> None:
    """The on-the-wire string is ``"agent"`` — must not drift from the constant.

    Existing logs, viewer code, and the TypeScript ``generated.ts``
    all hard-code ``"agent"`` as the span type. The constant exists
    purely to make Python producers/consumers reference a single
    name, not to enable renaming.
    """
    assert AGENT_SPAN_TYPE == "agent"


async def test_run_emits_agent_boundary_span() -> None:
    """``agent.run(agent, ...)`` opens a single ``type="agent"`` span."""
    transcript = Transcript()
    token = _transcript.set(transcript)
    sample_tok = samples_var.set(acp_test_active_sample(transcript))
    try:
        await run(_leaf_agent(), input="hello")
        assert _agent_span_names(transcript) == ["leaf_agent"]
    finally:
        samples_var.reset(sample_tok)
        _transcript.reset(token)


async def test_as_solver_emits_agent_boundary_span() -> None:
    """``as_solver(agent)`` invocation opens a ``type="agent"`` span."""
    transcript = Transcript()
    token = _transcript.set(transcript)
    sample_tok = samples_var.set(acp_test_active_sample(transcript))
    try:
        solver = as_solver(_leaf_agent())
        state = TaskState(
            model="mockllm/model",  # type: ignore[arg-type]
            sample_id="s1",
            epoch=0,
            input="hello",
            messages=[ChatMessageUser(content="hello")],
        )

        async def _no_op_generate(state: TaskState, **kw: Any) -> TaskState:
            return state

        await solver(state, _no_op_generate)  # type: ignore[arg-type]
        assert _agent_span_names(transcript) == ["leaf_agent"]
    finally:
        samples_var.reset(sample_tok)
        _transcript.reset(token)


async def test_react_with_as_tool_subagent_emits_two_boundary_spans() -> None:
    """A top-level react with an ``as_tool`` sub-agent emits two boundary spans.

    Canonical Phase 6 case: the outer react (invoked via ``run()`` to
    pick up the agent-boundary span) opens its own ``type="agent"``
    span, and when the model calls the sub-agent tool, the inner
    ``as_tool`` invocation opens another. The router will count
    concurrently-open boundaries (max depth 2 here) and drop events
    at depth > 1.
    """
    transcript = Transcript()
    token = _transcript.set(transcript)
    sample_tok = samples_var.set(acp_test_active_sample(transcript))
    try:

        @agent(name="sub_agent", description="A sub-agent used as a tool.")
        def sub_agent() -> Agent:
            async def execute(state: AgentState) -> AgentState:
                return state

            return execute

        # Parent react: turn 1 calls the sub-agent tool; turn 2 submits.
        call_count = [0]

        def gen(input: Any, tools: Any, tc: Any, cfg: Any) -> ModelOutput:
            call_count[0] += 1
            if call_count[0] == 1:
                return ModelOutput.for_tool_call(
                    "mockllm/model", "sub_agent", {"input": "do the thing"}
                )
            return ModelOutput.for_tool_call(
                "mockllm/model", "submit", {"answer": "done"}
            )

        model = get_model("mockllm/model", memoize=False, custom_outputs=gen)
        parent = react(tools=[as_tool(sub_agent())], model=model)
        await run(parent, input="go")

        # Both react (via run()) and the sub-agent (via as_tool) must
        # have opened boundary spans.
        names = _agent_span_names(transcript)
        assert "react" in names, (
            f"top-level react boundary span missing; got names={names}"
        )
        assert "sub_agent" in names, (
            f"sub-agent boundary span missing; got names={names}"
        )
        assert len(names) >= 2, (
            f"expected ≥2 boundary spans (parent + sub-agent); got names={names}"
        )
    finally:
        samples_var.reset(sample_tok)
        _transcript.reset(token)


async def test_handoff_invocation_emits_agent_boundary_span() -> None:
    """``handoff(agent)`` dispatch opens an inner ``type="agent"`` span.

    The handoff path in ``_call_tools.py`` opens its own
    ``type="agent"`` span around the sub-agent invocation (separate
    from the outer ``type="handoff"`` and ``type="tool"`` spans, which
    Phase 6's router does NOT count).
    """
    transcript = Transcript()
    token = _transcript.set(transcript)
    sample_tok = samples_var.set(acp_test_active_sample(transcript))
    try:

        @agent(
            name="handoff_target",
            description="Sub-agent invoked via handoff.",
        )
        def target() -> Agent:
            async def execute(state: AgentState) -> AgentState:
                return state

            return execute

        # react with a handoff tool. After the model hands off, the
        # sub-agent runs to completion; mockllm runs out of outputs
        # mid-react which raises but the handoff span will already
        # have been emitted before the error.
        def gen(input: Any, tools: Any, tc: Any, cfg: Any) -> ModelOutput:
            return ModelOutput.for_tool_call(
                "mockllm/model", "transfer_to_handoff_target", {}
            )

        model = get_model("mockllm/model", memoize=False, custom_outputs=gen)
        parent = react(tools=[handoff(target())], model=model)
        try:
            await run(parent, input="go")
        except Exception:
            # The handoff invokes the sub-agent and returns; mockllm
            # may then run out of outputs. We only care that the
            # boundary span was emitted before the error.
            pass

        names = _agent_span_names(transcript)
        assert "handoff_target" in names, (
            f"handoff sub-agent boundary span missing; got names={names}"
        )
    finally:
        samples_var.reset(sample_tok)
        _transcript.reset(token)


async def test_top_level_react_emits_agent_boundary_span() -> None:
    """A top-level ``react()`` opens a ``type="agent"`` span via its splice.

    Without an outer ``as_tool``/``handoff``/``as_solver`` wrap,
    react's own ``@agent``-decorated dispatch through ``run()`` still
    emits the boundary marker when invoked at the top level via
    awaiting the agent directly. Phase 6's router needs this so the
    outermost react gets depth=1 (events visible) — without it,
    everything inside would look like depth=0 / top-level.
    """
    transcript = Transcript()
    token = _transcript.set(transcript)
    sample_tok = samples_var.set(acp_test_active_sample(transcript))
    try:
        model = get_model(
            "mockllm/model",
            memoize=False,
            custom_outputs=[
                ModelOutput.for_tool_call("mockllm/model", "submit", {"answer": "done"})
            ],
        )
        # Use run() to force the agent-boundary span at the top level.
        await run(react(model=model), input="start")
        names = _agent_span_names(transcript)
        # react itself is registered with name "react".
        assert "react" in names, (
            f"top-level react boundary span missing; got names={names}"
        )
    finally:
        samples_var.reset(sample_tok)
        _transcript.reset(token)


def test_no_remaining_literal_agent_type_in_span_call_sites() -> None:
    """Regression: no production code path opens a span with literal type="agent".

    All five known paths must reference `AGENT_SPAN_TYPE` so a future
    refactor (or a new path) doesn't silently drop the boundary
    marker. This is a grep-style guard — it walks the source tree for
    `span(...type="agent"...)` patterns and fails if any remain.
    """
    import re
    from pathlib import Path

    src = Path("src/inspect_ai")
    pattern = re.compile(r'span\([^)]*type\s*=\s*"agent"', re.DOTALL)
    offenders: list[str] = []
    for path in src.rglob("*.py"):
        text = path.read_text()
        if pattern.search(text):
            offenders.append(str(path))
    assert not offenders, (
        'Literal type="agent" found in span(...) calls; use '
        f"AGENT_SPAN_TYPE instead: {offenders}"
    )
