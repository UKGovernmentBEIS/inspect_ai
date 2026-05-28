"""Tests for Phase 1 background dispatch.

Covers ``agent(background=True)``, the registry, ``_run_background``,
cap behaviour, and ``background=True|False|int`` parameter resolution.
The full lifecycle tools (agent_status, agent_wait, agent_cancel,
agent_list) land in Phase 2 — tests here use a small in-file helper
tool to introspect the registry where needed.
"""

from __future__ import annotations

import pytest

from inspect_ai import Task, eval
from inspect_ai.agent import deepagent, subagent
from inspect_ai.agent._deepagent.agent_tool import (
    AgentFuture,
    BackgroundRegistry,
    active_background_agents,
    current_background_registry,
)
from inspect_ai.agent._deepagent.deepagent import (
    DEFAULT_MAX_BACKGROUND,
    _resolve_background,
)
from inspect_ai.dataset import Sample
from inspect_ai.event._tool import ToolEvent
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.tool import Tool, tool

# ---------------------------------------------------------------------------
# Test-only helper: wait for a specific AgentFuture to complete and report
# its status. Stands in for Phase 2's agent_wait/agent_status during Phase 1
# testing. Lives in the test file so it isn't part of the production surface.
# ---------------------------------------------------------------------------


@tool
def _wait_test_helper() -> Tool:
    """Test-only tool: wait for a specific background agent to complete.

    Returns a synthesised status string we can assert on.
    """

    async def execute(agent_id: str) -> str:
        """Wait for a background agent to finish and return its status.

        Args:
            agent_id: The AGENT-N handle to wait on.
        """
        reg = current_background_registry()
        if reg is None:
            return "no-registry"
        future = reg.futures.get(agent_id)
        if future is None:
            return f"unknown:{agent_id}"
        await future.done.wait()
        if future.status == "completed":
            return f"completed:{future.result}"
        if future.status == "errored":
            return f"errored:{future.error}"
        return future.status

    return execute


@tool
def _snapshot_test_helper() -> Tool:
    """Test-only tool: snapshot the current registry.

    Returns a deterministic string of ``AGENT-N=status`` entries for
    assertions.
    """

    async def execute() -> str:
        """Snapshot the current background registry as a flat string."""
        reg = current_background_registry()
        if reg is None:
            return "no-registry"
        if not reg.futures:
            return "empty"
        items = [f"{aid}={f.status}" for aid, f in reg.futures.items()]
        return ",".join(items)

    return execute


def _submit(answer: str = "done") -> ModelOutput:
    return ModelOutput.for_tool_call(
        model="mockllm/model",
        tool_name="submit",
        tool_arguments={"answer": answer},
    )


def _spawn(subagent_type: str = "general", prompt: str = "Do work.") -> ModelOutput:
    return ModelOutput.for_tool_call(
        model="mockllm/model",
        tool_name="agent",
        tool_arguments={
            "subagent_type": subagent_type,
            "prompt": prompt,
            "background": True,
        },
    )


def _eval_deepagent(
    agent_kwargs: dict,
    outputs: list[ModelOutput],
    input: str = "Do the task",
    message_limit: int = 30,
) -> dict:
    agent_kwargs.setdefault("submit", True)
    da = deepagent(**agent_kwargs)
    task = Task(
        dataset=[Sample(input=input)],
        solver=da,
        message_limit=message_limit,
    )
    model = get_model("mockllm/model", custom_outputs=outputs)
    log = eval(task, model=model)[0]
    return {
        "log": log,
        "status": log.status,
        "messages": log.samples[0].messages if log.samples else [],
        "events": log.samples[0].events if log.samples else [],
    }


# ---------------------------------------------------------------------------
# Unit tests: parameter resolution and registry primitives
# ---------------------------------------------------------------------------


class TestResolveBackground:
    def test_true_default_cap(self) -> None:
        assert _resolve_background(True) == (True, DEFAULT_MAX_BACKGROUND)

    def test_false_disables(self) -> None:
        assert _resolve_background(False) == (False, 0)

    def test_positive_int_sets_cap(self) -> None:
        assert _resolve_background(4) == (True, 4)
        assert _resolve_background(1) == (True, 1)
        assert _resolve_background(100) == (True, 100)

    def test_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="positive integer"):
            _resolve_background(0)

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="positive integer"):
            _resolve_background(-1)

    def test_non_bool_non_int_raises(self) -> None:
        with pytest.raises(ValueError):
            _resolve_background("yes")  # type: ignore[arg-type]


class TestBackgroundRegistry:
    def test_counter_monotonic(self) -> None:
        reg = BackgroundRegistry(max_background=8)
        assert reg.next_id() == "AGENT-1"
        assert reg.next_id() == "AGENT-2"
        assert reg.next_id() == "AGENT-3"

    def test_running_count_excludes_terminal(self) -> None:
        reg = BackgroundRegistry(max_background=8)
        import anyio

        f1 = AgentFuture(agent_id="AGENT-1", span_id="x", subagent_name="r")
        f2 = AgentFuture(agent_id="AGENT-2", span_id="y", subagent_name="r")
        f2.status = "completed"
        f3 = AgentFuture(agent_id="AGENT-3", span_id="z", subagent_name="r")
        f3.status = "cancelled"
        f4 = AgentFuture(agent_id="AGENT-4", span_id="w", subagent_name="r")
        f4.status = "errored"
        reg.futures["AGENT-1"] = f1
        reg.futures["AGENT-2"] = f2
        reg.futures["AGENT-3"] = f3
        reg.futures["AGENT-4"] = f4
        # only f1 is running
        assert reg.running_count() == 1
        _ = anyio  # silence import-only check

    def test_active_background_agents_no_registry(self) -> None:
        # Outside a deepagent context, returns empty list (not error).
        assert active_background_agents() == []


# ---------------------------------------------------------------------------
# Schema tests: background=True vs False produces different agent tool shapes
# ---------------------------------------------------------------------------


class TestAgentToolSchema:
    def test_background_enabled_includes_param(self) -> None:
        from inspect_ai.agent._deepagent.agent_tool import agent_tool
        from inspect_ai.tool._tool_info import parse_tool_info

        sa = subagent(
            name="research",
            description="Gather info.",
            prompt="You are a research assistant.",
        )
        tool_obj = agent_tool(subagents=[sa], background_enabled=True)
        info = parse_tool_info(tool_obj)
        # Parameter is in the schema with a description.
        assert "background" in info.parameters.properties
        bg_param = info.parameters.properties["background"]
        assert bg_param.type == "boolean"
        assert bg_param.default is False
        assert bg_param.description and "background" in bg_param.description.lower()

    def test_background_disabled_omits_param(self) -> None:
        from inspect_ai.agent._deepagent.agent_tool import agent_tool
        from inspect_ai.tool._tool_info import parse_tool_info

        sa = subagent(
            name="research",
            description="Gather info.",
            prompt="You are a research assistant.",
        )
        tool_obj = agent_tool(subagents=[sa], background_enabled=False)
        info = parse_tool_info(tool_obj)
        # Parameter is completely absent from the schema.
        assert "background" not in info.parameters.properties


# ---------------------------------------------------------------------------
# E2E tests via mockllm
# ---------------------------------------------------------------------------


class TestBackgroundSpawn:
    """E2E test for the basic spawn path via mockllm.

    Multi-spawn and cap tests are unit-level (see ``TestDispatchBackground``
    below) because mockllm's shared output queue makes ordering across
    concurrent agents unreliable — the background subagent and parent
    pull from the same queue at unpredictable interleavings.
    """

    def test_basic_spawn_returns_handle(self) -> None:
        """agent(background=True) returns 'Dispatched AGENT-N.' immediately."""
        result = _eval_deepagent(
            agent_kwargs={},
            outputs=[
                _spawn("general", "Do background work."),
                _submit("background-done"),  # consumed by bg or parent
                _submit("parent-done"),  # consumed by the other
            ],
        )
        assert result["status"] == "success"
        agent_events = [
            e
            for e in result["events"]
            if isinstance(e, ToolEvent) and e.function == "agent"
        ]
        assert len(agent_events) == 1
        assert "AGENT-1" in str(agent_events[0].result)
        assert "Dispatched" in str(agent_events[0].result)

    def test_background_false_no_background_param(self) -> None:
        """deepagent(background=False) → agent tool has no background param."""
        # Spawning with background=True should fail because the parameter
        # isn't on the tool — model passes an unknown kwarg.
        result = _eval_deepagent(
            agent_kwargs={"background": False},
            outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="agent",
                    tool_arguments={
                        "subagent_type": "general",
                        "prompt": "Some prompt.",
                        "background": True,
                    },
                ),
                _submit("sync-result"),
                _submit("parent"),
            ],
        )
        agent_events = [
            e
            for e in result["events"]
            if isinstance(e, ToolEvent) and e.function == "agent"
        ]
        assert len(agent_events) == 1
        # If background arg was rejected by schema validation, error is set;
        # if dispatch ran sync, no "Dispatched AGENT-" handle appears.
        assert agent_events[0].error is not None or "Dispatched AGENT-" not in str(
            agent_events[0].result
        )


class TestDispatchBackground:
    """Unit tests against _dispatch_background.

    Covers cap behaviour and the monotonic counter without mockllm
    concurrency complications. Uses an in-loop anyio test so we can
    construct AgentFuture (needs an event loop for CancelScope) and use
    background() (needs sample.tg). The tests don't actually run a real
    subagent — they call _dispatch_background directly and assert on
    registry mutations.
    """

    @staticmethod
    def _stub_future(reg: BackgroundRegistry, name: str = "general") -> AgentFuture:
        """Manually allocate a running AgentFuture in the registry.

        Simulates a successful spawn without actually running anything.
        """
        import anyio

        agent_id = reg.next_id()
        future = AgentFuture(
            agent_id=agent_id,
            span_id="x",
            subagent_name=name,
            cancel_scope=anyio.CancelScope(),
            started_at=anyio.current_time(),
        )
        reg.futures[agent_id] = future
        return future

    async def test_counter_monotonic_across_spawns(self) -> None:
        """Sequential next_id() calls produce AGENT-1, AGENT-2, AGENT-3."""
        reg = BackgroundRegistry(max_background=8)
        token = _set_registry_for_test(reg)
        try:
            f1 = self._stub_future(reg)
            f2 = self._stub_future(reg)
            f3 = self._stub_future(reg)
            assert f1.agent_id == "AGENT-1"
            assert f2.agent_id == "AGENT-2"
            assert f3.agent_id == "AGENT-3"
            assert list(reg.futures.keys()) == ["AGENT-1", "AGENT-2", "AGENT-3"]
        finally:
            _reset_registry_for_test(token)

    async def test_counter_never_reuses_after_completion(self) -> None:
        """Completing AGENT-1 doesn't free the name — the next spawn is AGENT-2."""
        reg = BackgroundRegistry(max_background=8)
        token = _set_registry_for_test(reg)
        try:
            f1 = self._stub_future(reg)
            f1.status = "completed"
            f2 = self._stub_future(reg)
            assert f2.agent_id == "AGENT-2"
        finally:
            _reset_registry_for_test(token)

    async def test_cap_check_blocks_at_max(self) -> None:
        """When running_count() >= max_background, _dispatch_background raises."""
        from inspect_ai.agent._deepagent.agent_tool import _dispatch_background
        from inspect_ai.agent._deepagent.subagent import subagent as subagent_factory

        reg = BackgroundRegistry(max_background=2)
        token = _set_registry_for_test(reg)
        try:
            self._stub_future(reg)
            self._stub_future(reg)
            # Both running; cap is 2 → next dispatch should raise.
            sa = subagent_factory(
                name="general",
                description="d",
                prompt="p",
            )

            async def dummy_agent(state):
                return state

            with pytest.raises(Exception) as exc_info:
                _dispatch_background(
                    child_agent=dummy_agent,
                    sa=sa,
                    dispatch_input="ignored",
                    span_id="x",
                    forked=False,
                    from_message=None,
                )
            assert "Maximum 2" in str(exc_info.value)
            assert "agent_wait" in str(exc_info.value)
        finally:
            _reset_registry_for_test(token)

    async def test_cap_check_excludes_terminal_futures(self) -> None:
        """Completed/cancelled/errored futures don't count toward the cap."""
        from inspect_ai.agent._deepagent.subagent import subagent as subagent_factory

        reg = BackgroundRegistry(max_background=2)
        token = _set_registry_for_test(reg)
        try:
            # 5 futures, but only 1 running — cap of 2 still has 1 slot left.
            f1 = self._stub_future(reg)
            f2 = self._stub_future(reg)
            f3 = self._stub_future(reg)
            f4 = self._stub_future(reg)
            self._stub_future(reg)  # AGENT-5 stays running
            f1.status = "completed"
            f2.status = "cancelled"
            f3.status = "errored"
            f4.status = "completed"
            # AGENT-5 is the only running one
            assert reg.running_count() == 1
            # A new dispatch should NOT be blocked (1 < 2).
            # (We don't actually dispatch — just verify the count.)
            _ = subagent_factory  # marker; subagent factory imported for parity
        finally:
            _reset_registry_for_test(token)

    async def test_no_registry_raises_clear_error(self) -> None:
        """Calling _dispatch_background outside a deepagent context raises."""
        from inspect_ai.agent._deepagent.agent_tool import _dispatch_background
        from inspect_ai.agent._deepagent.subagent import subagent as subagent_factory

        # No registry set on the contextvar
        sa = subagent_factory(name="general", description="d", prompt="p")

        async def dummy_agent(state):
            return state

        with pytest.raises(Exception) as exc_info:
            _dispatch_background(
                child_agent=dummy_agent,
                sa=sa,
                dispatch_input="ignored",
                span_id="x",
                forked=False,
                from_message=None,
            )
        assert "Background dispatch is not available" in str(exc_info.value)


def _set_registry_for_test(reg: BackgroundRegistry):
    """Wrapper around set_background_registry for tests."""
    from inspect_ai.agent._deepagent.agent_tool import set_background_registry

    return set_background_registry(reg)


def _reset_registry_for_test(token):
    from inspect_ai.agent._deepagent.agent_tool import reset_background_registry

    reset_background_registry(token)


class TestBackgroundExecution:
    """E2E tests that exercise actual background execution.

    Each subagent gets its own mockllm instance so the parent's and the
    background's model output queues don't compete on shared state.
    ``get_model("mockllm/model", custom_outputs=...)`` bypasses memoization
    (see ``model/_model.py:1701-1702``) so each call returns a fresh queue.
    """

    @staticmethod
    def _build_subagent(name: str, outputs: list[ModelOutput]):
        """Construct a subagent with its own mockllm instance."""
        from inspect_ai.agent._deepagent.subagent import subagent as subagent_factory

        bg_model = get_model("mockllm/model", custom_outputs=outputs)
        return subagent_factory(
            name=name,
            description=f"Background {name} subagent.",
            prompt=f"You are a {name} agent.",
            model=bg_model,
        )

    def test_background_subagent_actually_runs(self) -> None:
        """Spawn a background subagent that submits its answer.

        Parent waits via the test helper and confirms the bg completed
        with the expected answer.
        """
        bg_sa = self._build_subagent(
            "research",
            [
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="submit",
                    tool_arguments={"answer": "found X"},
                ),
            ],
        )
        parent_outputs = [
            _spawn("research", "Find X."),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="_wait_test_helper",
                tool_arguments={"agent_id": "AGENT-1"},
            ),
            _submit("done"),
        ]
        result = _eval_deepagent(
            agent_kwargs={
                "subagents": [bg_sa],
                "tools": [_wait_test_helper()],
            },
            outputs=parent_outputs,
        )
        assert result["status"] == "success"
        wait_events = [
            e
            for e in result["events"]
            if isinstance(e, ToolEvent) and e.function == "_wait_test_helper"
        ]
        assert len(wait_events) == 1
        assert "completed:found X" in str(wait_events[0].result)

    def test_multiple_backgrounds_run_concurrently(self) -> None:
        """Spawn two background subagents with different models.

        Wait for both, verify each completed with its own answer.
        """
        bg_a = self._build_subagent(
            "alpha",
            [
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="submit",
                    tool_arguments={"answer": "alpha-done"},
                ),
            ],
        )
        bg_b = self._build_subagent(
            "beta",
            [
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="submit",
                    tool_arguments={"answer": "beta-done"},
                ),
            ],
        )
        parent_outputs = [
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="agent",
                tool_arguments={
                    "subagent_type": "alpha",
                    "prompt": "Do A.",
                    "background": True,
                },
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="agent",
                tool_arguments={
                    "subagent_type": "beta",
                    "prompt": "Do B.",
                    "background": True,
                },
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="_wait_test_helper",
                tool_arguments={"agent_id": "AGENT-1"},
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="_wait_test_helper",
                tool_arguments={"agent_id": "AGENT-2"},
            ),
            _submit("done"),
        ]
        result = _eval_deepagent(
            agent_kwargs={
                "subagents": [bg_a, bg_b],
                "tools": [_wait_test_helper()],
            },
            outputs=parent_outputs,
        )
        assert result["status"] == "success"
        wait_events = [
            e
            for e in result["events"]
            if isinstance(e, ToolEvent) and e.function == "_wait_test_helper"
        ]
        assert len(wait_events) == 2
        results = [str(e.result) for e in wait_events]
        assert "completed:alpha-done" in results[0]
        assert "completed:beta-done" in results[1]

    def test_e2e_cap_rejection(self) -> None:
        """E2E cap test: with background=2, the third spawn attempt fails.

        The first two background subagents must remain in "running"
        state when the third spawn is attempted, otherwise the cap check
        (which counts only running futures) won't fire. We give each bg
        a tool that blocks indefinitely; they get cancelled at sample end.
        """
        from inspect_ai.agent._deepagent.subagent import subagent as subagent_factory

        @tool
        def _block_helper() -> Tool:
            """Test-only tool that blocks until the sample is cancelled."""

            async def execute() -> str:
                """Block forever (returns only via cancellation)."""
                import anyio

                await anyio.sleep(60)
                return "done"

            return execute

        def _build_blocking_subagent(name: str):
            """Build a subagent whose only model output calls _block_helper.

            The subagent stays in 'running' state until cancellation.
            """
            bg_model = get_model(
                "mockllm/model",
                custom_outputs=[
                    ModelOutput.for_tool_call(
                        model="mockllm/model",
                        tool_name="_block_helper",
                        tool_arguments={},
                    ),
                ],
            )
            return subagent_factory(
                name=name,
                description=f"Background {name} subagent.",
                prompt=f"You are a {name} agent.",
                model=bg_model,
                extra_tools=[_block_helper()],
            )

        bg_a = _build_blocking_subagent("alpha")
        bg_b = _build_blocking_subagent("beta")
        bg_c = _build_blocking_subagent("gamma")  # never actually spawned

        parent_outputs = [
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="agent",
                tool_arguments={
                    "subagent_type": "alpha",
                    "prompt": "A",
                    "background": True,
                },
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="agent",
                tool_arguments={
                    "subagent_type": "beta",
                    "prompt": "B",
                    "background": True,
                },
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="agent",
                tool_arguments={
                    "subagent_type": "gamma",
                    "prompt": "C — should fail at cap",
                    "background": True,
                },
            ),
            _submit("done"),
        ]
        result = _eval_deepagent(
            agent_kwargs={
                "background": 2,
                "subagents": [bg_a, bg_b, bg_c],
            },
            outputs=parent_outputs,
        )
        assert result["status"] == "success"
        agent_events = [
            e
            for e in result["events"]
            if isinstance(e, ToolEvent) and e.function == "agent"
        ]
        assert len(agent_events) == 3
        assert agent_events[0].error is None
        assert agent_events[1].error is None
        assert agent_events[2].error is not None
        assert "Maximum 2" in agent_events[2].error.message


class TestRegistryIsolation:
    """ContextVar isolation between nested deepagent scopes — unit-level."""

    async def test_nested_set_creates_fresh_registry(self) -> None:
        """Each ContextVar.set() creates a new scope.

        Resetting the inner token restores the outer registry intact.
        """
        outer = BackgroundRegistry(max_background=8)
        outer_token = _set_registry_for_test(outer)
        try:
            # Allocate in outer registry
            outer.next_id()  # AGENT-1
            outer.next_id()  # AGENT-2
            assert outer.counter == 2

            # Set inner registry — outer is shadowed
            inner = BackgroundRegistry(max_background=4)
            inner_token = _set_registry_for_test(inner)
            try:
                assert current_background_registry() is inner
                # Inner allocations start from 1
                inner.next_id()  # AGENT-1
                assert inner.counter == 1
                # Outer is untouched
                assert outer.counter == 2
            finally:
                _reset_registry_for_test(inner_token)

            # After resetting inner, outer is restored
            assert current_background_registry() is outer
            assert outer.counter == 2
        finally:
            _reset_registry_for_test(outer_token)

    async def test_active_background_agents_reads_current(self) -> None:
        """active_background_agents() returns only the current scope's futures.

        Outer scope's futures are invisible from inner.
        """
        outer = BackgroundRegistry(max_background=8)
        outer_token = _set_registry_for_test(outer)
        try:
            # Stub one running future in outer
            import anyio

            outer.futures["AGENT-1"] = AgentFuture(
                agent_id="AGENT-1",
                span_id="x",
                subagent_name="general",
                cancel_scope=anyio.CancelScope(),
                started_at=anyio.current_time(),
            )
            assert len(active_background_agents()) == 1

            inner = BackgroundRegistry(max_background=4)
            inner_token = _set_registry_for_test(inner)
            try:
                # Inner sees no agents (its own registry is empty)
                assert active_background_agents() == []
            finally:
                _reset_registry_for_test(inner_token)

            # Restored: outer's one agent is visible again
            assert len(active_background_agents()) == 1
        finally:
            _reset_registry_for_test(outer_token)
