"""Tests for Phase 1 background dispatch.

Covers ``agent(background=True)``, the registry, ``_run_background``,
cap behaviour, and ``background=True|False|int`` parameter resolution.
The full lifecycle tools (agent_status, agent_wait, agent_cancel,
agent_list) land in Phase 2 — tests here use a small in-file helper
tool to introspect the registry where needed.
"""

from __future__ import annotations

import anyio
import pytest

from inspect_ai import Task, eval
from inspect_ai.agent import deepagent, subagent
from inspect_ai.agent._deepagent.agent_tool import (
    AgentFuture,
    BackgroundRegistry,
    active_background_agents,
    background_registry,
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
    # These are background-dispatch tests; deepagent()'s production default is
    # background=False, so enable it here unless a test opts out explicitly
    # (e.g. the disabled-surface and ValueError cases pass background=...).
    agent_kwargs.setdefault("background", True)
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


@tool
def _block_helper() -> Tool:
    """Test-only tool that blocks until the sample is cancelled.

    Used to keep a background subagent in 'running' state for the
    duration of a test (e.g. while the parent peeks/cancels it).
    """

    async def execute() -> str:
        """Block for a long time (returns only via cancellation)."""
        import anyio

        await anyio.sleep(60)
        return "done"

    return execute


@tool
def _say_helper() -> Tool:
    """Test-only tool: emit a chunk of text, then block.

    Lets a test seed a known last-assistant message before the subagent
    parks in 'running' state so the status peek has content to report.
    """

    async def execute(text: str) -> str:
        """Return the provided text (becomes a prior tool result).

        Args:
            text: Text to echo back as the tool result.
        """
        return text

    return execute


def _build_submit_subagent(name: str, answer: str):
    """Build a subagent whose only model output submits ``answer``."""
    from inspect_ai.agent._deepagent.subagent import subagent as subagent_factory

    bg_model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": answer},
            ),
        ],
    )
    return subagent_factory(
        name=name,
        description=f"Background {name} subagent.",
        prompt=f"You are a {name} agent.",
        model=bg_model,
    )


def _build_blocking_subagent(name: str, outputs: list[ModelOutput] | None = None):
    """Build a subagent that parks in 'running' state until cancellation.

    By default its only model output calls ``_block_helper``. Pass
    ``outputs`` to prepend other turns (e.g. a ``_say_helper`` call to
    seed a last-assistant message) before it blocks.
    """
    from inspect_ai.agent._deepagent.subagent import subagent as subagent_factory

    block_call = ModelOutput.for_tool_call(
        model="mockllm/model",
        tool_name="_block_helper",
        tool_arguments={},
    )
    custom_outputs = (outputs or []) + [block_call]
    bg_model = get_model("mockllm/model", custom_outputs=custom_outputs)
    return subagent_factory(
        name=name,
        description=f"Background {name} subagent.",
        prompt=f"You are a {name} agent.",
        model=bg_model,
        extra_tools=[_block_helper(), _say_helper()],
    )


def _agent_call(
    subagent_type: str, prompt: str = "go", background: bool = True
) -> ModelOutput:
    return ModelOutput.for_tool_call(
        model="mockllm/model",
        tool_name="agent",
        tool_arguments={
            "subagent_type": subagent_type,
            "prompt": prompt,
            "background": background,
        },
    )


def _tool_call(tool_name: str, **arguments) -> ModelOutput:
    return ModelOutput.for_tool_call(
        model="mockllm/model",
        tool_name=tool_name,
        tool_arguments=arguments,
    )


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
        with background_registry(reg):
            f1 = self._stub_future(reg)
            f2 = self._stub_future(reg)
            f3 = self._stub_future(reg)
            assert f1.agent_id == "AGENT-1"
            assert f2.agent_id == "AGENT-2"
            assert f3.agent_id == "AGENT-3"
            assert list(reg.futures.keys()) == ["AGENT-1", "AGENT-2", "AGENT-3"]

    async def test_counter_never_reuses_after_completion(self) -> None:
        """Completing AGENT-1 doesn't free the name — the next spawn is AGENT-2."""
        reg = BackgroundRegistry(max_background=8)
        with background_registry(reg):
            f1 = self._stub_future(reg)
            f1.status = "completed"
            f2 = self._stub_future(reg)
            assert f2.agent_id == "AGENT-2"

    async def test_cap_check_blocks_at_max(self) -> None:
        """When running_count() >= max_background, _dispatch_background raises."""
        from inspect_ai.agent._deepagent.agent_tool import _dispatch_background
        from inspect_ai.agent._deepagent.subagent import subagent as subagent_factory

        reg = BackgroundRegistry(max_background=2)
        with background_registry(reg):
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

    async def test_cap_check_excludes_terminal_futures(self) -> None:
        """Completed/cancelled/errored futures don't count toward the cap."""
        from inspect_ai.agent._deepagent.subagent import subagent as subagent_factory

        reg = BackgroundRegistry(max_background=2)
        with background_registry(reg):
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
        with background_registry(outer):
            # Allocate in outer registry
            outer.next_id()  # AGENT-1
            outer.next_id()  # AGENT-2
            assert outer.counter == 2

            # Set inner registry — outer is shadowed
            inner = BackgroundRegistry(max_background=4)
            with background_registry(inner):
                assert current_background_registry() is inner
                # Inner allocations start from 1
                inner.next_id()  # AGENT-1
                assert inner.counter == 1
                # Outer is untouched
                assert outer.counter == 2

            # After resetting inner, outer is restored
            assert current_background_registry() is outer
            assert outer.counter == 2

    async def test_active_background_agents_reads_current(self) -> None:
        """active_background_agents() returns only the current scope's futures.

        Outer scope's futures are invisible from inner.
        """
        outer = BackgroundRegistry(max_background=8)
        with background_registry(outer):
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
            with background_registry(inner):
                # Inner sees no agents (its own registry is empty)
                assert active_background_agents() == []

            # Restored: outer's one agent is visible again
            assert len(active_background_agents()) == 1


# ---------------------------------------------------------------------------
# Phase 2 — lifecycle tools (agent_status / agent_wait / agent_cancel /
# agent_list)
# ---------------------------------------------------------------------------


def _events_for(result: dict, function: str) -> list[ToolEvent]:
    return [
        e
        for e in result["events"]
        if isinstance(e, ToolEvent) and e.function == function
    ]


class TestLifecycleToolsSurfaced:
    """The four lifecycle tools appear only when background is enabled."""

    def _tool_names(self, da_kwargs: dict) -> set[str]:
        from inspect_ai._util.registry import is_registry_object, registry_info
        from inspect_ai.tool._tool_def import ToolDef

        # Drive a no-op eval and inspect the tools the model was offered by
        # reading the first model event's available tools is overkill; instead
        # build the agent and introspect via a probe tool call is also complex.
        # Simplest: run a minimal eval that immediately submits, then read the
        # tools from the model event.
        result = _eval_deepagent(
            agent_kwargs=da_kwargs,
            outputs=[_submit("done")],
        )
        names: set[str] = set()
        from inspect_ai.event._model import ModelEvent

        for e in result["events"]:
            if isinstance(e, ModelEvent):
                for t in e.tools:
                    names.add(t.name)
                break
        # silence unused imports
        _ = (is_registry_object, registry_info, ToolDef)
        return names

    def test_lifecycle_tools_present_when_enabled(self) -> None:
        names = self._tool_names({})
        assert {"agent_status", "agent_wait", "agent_cancel", "agent_list"} <= names

    def test_lifecycle_tools_absent_when_disabled(self) -> None:
        names = self._tool_names({"background": False})
        assert "agent_status" not in names
        assert "agent_wait" not in names
        assert "agent_cancel" not in names
        assert "agent_list" not in names


class TestAgentStatus:
    def test_status_completed_includes_result(self) -> None:
        bg = _build_submit_subagent("research", "the findings")
        result = _eval_deepagent(
            agent_kwargs={"subagents": [bg]},
            outputs=[
                _agent_call("research"),
                # Wait for it first so it is completed when we check status.
                _tool_call("agent_wait", agent_ids=["AGENT-1"]),
                _tool_call("agent_status", agent_id="AGENT-1"),
                _submit("done"),
            ],
        )
        assert result["status"] == "success"
        status_events = _events_for(result, "agent_status")
        assert len(status_events) == 1
        body = str(status_events[0].result)
        assert "AGENT-1" in body
        assert "completed" in body
        assert "the findings" in body

    def test_status_running_includes_peek(self) -> None:
        bg = _build_blocking_subagent(
            "worker",
            outputs=[_tool_call("_say_helper", text="searching the corpus")],
        )
        result = _eval_deepagent(
            agent_kwargs={"subagents": [bg]},
            outputs=[
                _agent_call("worker"),
                # Give the bg a moment to run its _say_helper turn, then peek.
                _tool_call("agent_status", agent_id="AGENT-1"),
                _submit("done"),
            ],
        )
        assert result["status"] == "success"
        status_events = _events_for(result, "agent_status")
        assert len(status_events) == 1
        body = str(status_events[0].result)
        assert "AGENT-1" in body
        assert "running" in body
        # Peek fields present
        assert "elapsed" in body
        assert "messages" in body

    def test_status_unknown_id_reports_as_content(self) -> None:
        # Lifecycle tools never raise — an unknown id is reported as
        # content, and the tool call itself succeeds.
        bg = _build_submit_subagent("research", "x")
        result = _eval_deepagent(
            agent_kwargs={"subagents": [bg]},
            outputs=[
                _tool_call("agent_status", agent_id="AGENT-99"),
                _submit("done"),
            ],
        )
        status_events = _events_for(result, "agent_status")
        assert len(status_events) == 1
        assert status_events[0].error is None
        assert "Unknown agent id" in str(status_events[0].result)


class TestAgentWait:
    def test_wait_all_returns_both(self) -> None:
        bg_a = _build_submit_subagent("alpha", "alpha-result")
        bg_b = _build_submit_subagent("beta", "beta-result")
        result = _eval_deepagent(
            agent_kwargs={"subagents": [bg_a, bg_b]},
            outputs=[
                _agent_call("alpha"),
                _agent_call("beta"),
                _tool_call("agent_wait", agent_ids=["AGENT-1", "AGENT-2"], mode="all"),
                _submit("done"),
            ],
        )
        assert result["status"] == "success"
        wait_events = _events_for(result, "agent_wait")
        assert len(wait_events) == 1
        body = str(wait_events[0].result)
        assert "AGENT-1" in body and "AGENT-2" in body
        assert "alpha-result" in body
        assert "beta-result" in body

    def test_wait_any_returns_on_first(self) -> None:
        # One completes (submit), one blocks. mode="any" must return without
        # waiting for the blocker.
        bg_fast = _build_submit_subagent("fast", "fast-result")
        bg_slow = _build_blocking_subagent("slow")
        result = _eval_deepagent(
            agent_kwargs={"subagents": [bg_fast, bg_slow]},
            outputs=[
                _agent_call("fast"),
                _agent_call("slow"),
                _tool_call("agent_wait", agent_ids=["AGENT-1", "AGENT-2"], mode="any"),
                _submit("done"),
            ],
        )
        assert result["status"] == "success"
        wait_events = _events_for(result, "agent_wait")
        assert len(wait_events) == 1
        body = str(wait_events[0].result)
        # The fast one completed with its result.
        assert "fast-result" in body

    def test_wait_timeout_reports_running(self) -> None:
        bg = _build_blocking_subagent("slow")
        result = _eval_deepagent(
            agent_kwargs={"subagents": [bg]},
            outputs=[
                _agent_call("slow"),
                _tool_call("agent_wait", agent_ids=["AGENT-1"], timeout=0.2),
                _submit("done"),
            ],
        )
        assert result["status"] == "success"
        wait_events = _events_for(result, "agent_wait")
        assert len(wait_events) == 1
        body = str(wait_events[0].result)
        # Did not lie — still running after timeout.
        assert "AGENT-1" in body
        assert "running" in body

    def test_wait_empty_ids_reports_as_content(self) -> None:
        bg = _build_submit_subagent("research", "x")
        result = _eval_deepagent(
            agent_kwargs={"subagents": [bg]},
            outputs=[
                _tool_call("agent_wait", agent_ids=[]),
                _submit("done"),
            ],
        )
        wait_events = _events_for(result, "agent_wait")
        assert len(wait_events) == 1
        assert wait_events[0].error is None
        assert "No agent_ids" in str(wait_events[0].result)

    def test_wait_unknown_id_reports_as_content(self) -> None:
        bg = _build_submit_subagent("research", "x")
        result = _eval_deepagent(
            agent_kwargs={"subagents": [bg]},
            outputs=[
                _tool_call("agent_wait", agent_ids=["AGENT-77"]),
                _submit("done"),
            ],
        )
        wait_events = _events_for(result, "agent_wait")
        assert len(wait_events) == 1
        assert wait_events[0].error is None
        assert "Unknown agent id" in str(wait_events[0].result)

    def test_wait_mixed_known_and_unknown(self) -> None:
        # A known completed agent plus an unknown id: the known result is
        # returned and the unknown id is noted — no raise.
        bg = _build_submit_subagent("research", "the-result")
        result = _eval_deepagent(
            agent_kwargs={"subagents": [bg]},
            outputs=[
                _agent_call("research"),
                _tool_call("agent_wait", agent_ids=["AGENT-1", "AGENT-X"]),
                _submit("done"),
            ],
        )
        wait_events = _events_for(result, "agent_wait")
        assert len(wait_events) == 1
        assert wait_events[0].error is None
        body = str(wait_events[0].result)
        assert "the-result" in body
        assert "AGENT-X" in body


class TestAgentCancel:
    def test_cancel_running_agent(self) -> None:
        bg = _build_blocking_subagent("slow")
        result = _eval_deepagent(
            agent_kwargs={"subagents": [bg]},
            outputs=[
                _agent_call("slow"),
                _tool_call("agent_cancel", agent_id="AGENT-1"),
                # Confirm via status that it is cancelled.
                _tool_call("agent_status", agent_id="AGENT-1"),
                _submit("done"),
            ],
        )
        assert result["status"] == "success"
        cancel_events = _events_for(result, "agent_cancel")
        assert len(cancel_events) == 1
        assert "AGENT-1" in str(cancel_events[0].result)
        status_events = _events_for(result, "agent_status")
        assert "cancelled" in str(status_events[0].result)

    def test_cancel_completed_is_noop(self) -> None:
        bg = _build_submit_subagent("research", "done-result")
        result = _eval_deepagent(
            agent_kwargs={"subagents": [bg]},
            outputs=[
                _agent_call("research"),
                _tool_call("agent_wait", agent_ids=["AGENT-1"]),
                # Cancel after completion — should not error, reports completed.
                _tool_call("agent_cancel", agent_id="AGENT-1"),
                _submit("done"),
            ],
        )
        assert result["status"] == "success"
        cancel_events = _events_for(result, "agent_cancel")
        assert len(cancel_events) == 1
        assert cancel_events[0].error is None
        assert "completed" in str(cancel_events[0].result)


class TestAgentList:
    def test_list_empty(self) -> None:
        bg = _build_submit_subagent("research", "x")
        result = _eval_deepagent(
            agent_kwargs={"subagents": [bg]},
            outputs=[
                _tool_call("agent_list"),
                _submit("done"),
            ],
        )
        list_events = _events_for(result, "agent_list")
        assert len(list_events) == 1
        assert "No background agents" in str(list_events[0].result)

    def test_list_populated(self) -> None:
        bg_a = _build_submit_subagent("alpha", "a")
        bg_b = _build_submit_subagent("beta", "b")
        result = _eval_deepagent(
            agent_kwargs={"subagents": [bg_a, bg_b]},
            outputs=[
                _agent_call("alpha"),
                _agent_call("beta"),
                _tool_call("agent_wait", agent_ids=["AGENT-1", "AGENT-2"]),
                _tool_call("agent_list"),
                _submit("done"),
            ],
        )
        list_events = _events_for(result, "agent_list")
        assert len(list_events) == 1
        body = str(list_events[0].result)
        assert "AGENT-1" in body and "AGENT-2" in body

    def test_list_status_filter(self) -> None:
        # One completed, one running. Filter to running should show only the
        # blocker.
        bg_done = _build_submit_subagent("done_one", "r")
        bg_run = _build_blocking_subagent("run_one")
        result = _eval_deepagent(
            agent_kwargs={"subagents": [bg_done, bg_run]},
            outputs=[
                _agent_call("done_one"),
                _agent_call("run_one"),
                _tool_call("agent_wait", agent_ids=["AGENT-1"]),  # ensure 1 done
                _tool_call("agent_list", status_filter="running"),
                _submit("done"),
            ],
        )
        list_events = _events_for(result, "agent_list")
        assert len(list_events) == 1
        body = str(list_events[0].result)
        # AGENT-2 (run_one) is the only running one.
        assert "AGENT-2" in body
        assert "AGENT-1" not in body


class TestFormatStatusUnit:
    """Unit tests for _format_future_status / _peek_messages."""

    async def test_running_block_truncates_last_message(self) -> None:
        from inspect_ai.agent._agent import AgentState
        from inspect_ai.agent._deepagent.lifecycle_tools import _format_future_status
        from inspect_ai.model._chat_message import ChatMessageAssistant

        future = AgentFuture(
            agent_id="AGENT-1",
            span_id="x",
            subagent_name="research",
            cancel_scope=anyio.CancelScope(),
            started_at=anyio.current_time(),
        )
        big = "Z" * 5000
        future.child_state = AgentState(messages=[ChatMessageAssistant(content=big)])
        block = _format_future_status(future)
        assert "AGENT-1" in block
        assert "running" in block
        # The latest line must be present but truncated well under 5000 chars.
        assert "latest:" in block
        assert len(block) < 4000

    async def test_completed_block_has_result(self) -> None:
        from inspect_ai.agent._deepagent.lifecycle_tools import _format_future_status

        future = AgentFuture(
            agent_id="AGENT-2",
            span_id="y",
            subagent_name="general",
            cancel_scope=anyio.CancelScope(),
            started_at=anyio.current_time(),
        )
        future.status = "completed"
        future.result = "the answer"
        block = _format_future_status(future)
        assert "AGENT-2" in block
        assert "completed" in block
        assert "the answer" in block

    async def test_init_window_no_child_state(self) -> None:
        from inspect_ai.agent._deepagent.lifecycle_tools import _format_future_status

        future = AgentFuture(
            agent_id="AGENT-3",
            span_id="z",
            subagent_name="research",
            cancel_scope=anyio.CancelScope(),
            started_at=anyio.current_time(),
        )
        # child_state is None (default) — should not raise.
        block = _format_future_status(future)
        assert "AGENT-3" in block
        assert "running" in block
        assert "messages: 0" in block


class TestLifecycleViewers:
    """Custom ToolCallViewer titles render from call arguments."""

    def test_status_viewer_title(self) -> None:
        from inspect_ai.agent._deepagent.lifecycle_tools import _status_viewer
        from inspect_ai.tool._tool_call import ToolCall

        view = _status_viewer(
            ToolCall(id="1", function="agent_status", arguments={"agent_id": "AGENT-1"})
        )
        assert view.call is not None
        assert view.call.title == "agent_status: AGENT-1"

    def test_wait_viewer_title(self) -> None:
        from inspect_ai.agent._deepagent.lifecycle_tools import _wait_viewer
        from inspect_ai.tool._tool_call import ToolCall

        view = _wait_viewer(
            ToolCall(
                id="1",
                function="agent_wait",
                arguments={"agent_ids": ["AGENT-1", "AGENT-2"], "mode": "any"},
            )
        )
        assert view.call is not None
        assert view.call.title == "agent_wait: AGENT-1, AGENT-2 (any)"

    def test_list_viewer_title_filtered(self) -> None:
        from inspect_ai.agent._deepagent.lifecycle_tools import _list_viewer
        from inspect_ai.tool._tool_call import ToolCall

        view = _list_viewer(
            ToolCall(
                id="1",
                function="agent_list",
                arguments={"status_filter": "running"},
            )
        )
        assert view.call is not None
        assert view.call.title == "agent_list: running"


# ---------------------------------------------------------------------------
# Phase 4: periodic background-agent reminder (via on_continue)
# ---------------------------------------------------------------------------


def _idle(text: str = "still working") -> ModelOutput:
    """A parent turn with no tool calls (advances the reminder counter)."""
    return ModelOutput.from_content(model="mockllm/model", content=text)


def _reminder_messages(result: dict) -> list:
    """Parent ChatMessageUser reminders injected by the on_continue wrapper."""
    from inspect_ai.model._chat_message import ChatMessageUser

    return [
        m
        for m in result["messages"]
        if isinstance(m, ChatMessageUser) and "Automatic reminder" in m.text
    ]


class TestUsedBackgroundTool:
    """Unit tests for the interaction detector that gates the counter."""

    def _state(self, *tool_calls):
        from inspect_ai.agent._agent import AgentState
        from inspect_ai.model._chat_message import ChatMessageAssistant

        return AgentState(
            messages=[
                ChatMessageAssistant(
                    content="thinking", tool_calls=list(tool_calls) or None
                )
            ]
        )

    def _call(self, function: str, **arguments):
        from inspect_ai.tool._tool_call import ToolCall

        return ToolCall(id="1", function=function, arguments=arguments)

    def test_lifecycle_tool_detected(self) -> None:
        from inspect_ai.agent._deepagent.lifecycle_tools import _used_background_tool

        for name in ("agent_status", "agent_wait", "agent_cancel", "agent_list"):
            assert _used_background_tool(self._state(self._call(name))) is True

    def test_background_dispatch_detected(self) -> None:
        from inspect_ai.agent._deepagent.lifecycle_tools import _used_background_tool

        st = self._state(
            self._call("agent", subagent_type="r", prompt="go", background=True)
        )
        assert _used_background_tool(st) is True

    def test_sync_dispatch_not_detected(self) -> None:
        from inspect_ai.agent._deepagent.lifecycle_tools import _used_background_tool

        st = self._state(
            self._call("agent", subagent_type="r", prompt="go", background=False)
        )
        assert _used_background_tool(st) is False

    def test_neutral_tool_not_detected(self) -> None:
        from inspect_ai.agent._deepagent.lifecycle_tools import _used_background_tool

        assert _used_background_tool(self._state(self._call("bash"))) is False

    def test_text_only_turn_not_detected(self) -> None:
        from inspect_ai.agent._deepagent.lifecycle_tools import _used_background_tool

        assert _used_background_tool(self._state()) is False

    def test_no_assistant_message(self) -> None:
        from inspect_ai.agent._agent import AgentState
        from inspect_ai.agent._deepagent.lifecycle_tools import _used_background_tool

        assert _used_background_tool(AgentState(messages=[])) is False


class TestBackgroundReminderMessage:
    """Unit tests for the passive reminder formatter."""

    def _future(self, agent_id: str, name: str, status: str = "running") -> AgentFuture:
        future = AgentFuture(
            agent_id=agent_id,
            span_id="x",
            subagent_name=name,
            cancel_scope=anyio.CancelScope(),
            started_at=anyio.current_time(),
        )
        future.status = status  # type: ignore[assignment]
        return future

    async def test_running_is_passive_no_collect_line(self) -> None:
        from inspect_ai.agent._deepagent.lifecycle_tools import (
            background_reminder_message,
        )

        msg = background_reminder_message([self._future("AGENT-1", "research")])
        assert msg is not None
        text = msg.text
        assert "AGENT-1" in text and "research" in text
        assert "no action needed" in text.lower()
        assert "Still running" in text
        # running agents must not be framed as something to collect
        assert "collect" not in text.lower()

    async def test_completed_has_collect_line(self) -> None:
        from inspect_ai.agent._deepagent.lifecycle_tools import (
            background_reminder_message,
        )

        msg = background_reminder_message(
            [self._future("AGENT-2", "general", "completed")]
        )
        assert msg is not None
        assert "collect" in msg.text.lower()
        assert "agent_status('AGENT-2')" in msg.text

    async def test_errored_listed_as_finished(self) -> None:
        from inspect_ai.agent._deepagent.lifecycle_tools import (
            background_reminder_message,
        )

        msg = background_reminder_message(
            [self._future("AGENT-3", "general", "errored")]
        )
        assert msg is not None
        assert "AGENT-3" in msg.text
        assert "errored" in msg.text

    async def test_only_cancelled_returns_none(self) -> None:
        from inspect_ai.agent._deepagent.lifecycle_tools import (
            background_reminder_message,
        )

        assert (
            background_reminder_message(
                [self._future("AGENT-4", "general", "cancelled")]
            )
            is None
        )

    async def test_empty_returns_none(self) -> None:
        from inspect_ai.agent._deepagent.lifecycle_tools import (
            background_reminder_message,
        )

        assert background_reminder_message([]) is None


class TestReminderE2E:
    """End-to-end: the on_continue forgetting-backstop reminder."""

    def test_fires_after_idle_turns(self) -> None:
        bg_run = _build_blocking_subagent("run_one")
        result = _eval_deepagent(
            agent_kwargs={"subagents": [bg_run]},
            outputs=[
                _agent_call("run_one"),  # dispatch (counter resets to 0)
                _idle(),  # 1
                _idle(),  # 2
                _idle(),  # 3
                _idle(),  # 4
                _idle(),  # 5 -> reminder injected
                _submit("done"),
            ],
        )
        reminders = _reminder_messages(result)
        assert len(reminders) >= 1
        text = reminders[0].text
        assert "AGENT-1" in text
        assert "run_one" in text
        assert "Still running" in text

    def test_resets_on_interaction(self) -> None:
        # 4 idles, an agent_status interaction (resets), then 4 more idles.
        # The counter never reaches REMINDER_INTERVAL (5), so no reminder.
        bg_run = _build_blocking_subagent("run_one")
        result = _eval_deepagent(
            agent_kwargs={"subagents": [bg_run]},
            outputs=[
                _agent_call("run_one"),
                _idle(),
                _idle(),
                _idle(),
                _idle(),
                _tool_call("agent_status", agent_id="AGENT-1"),  # resets counter
                _idle(),
                _idle(),
                _idle(),
                _idle(),
                _submit("done"),
            ],
            message_limit=40,
        )
        assert _reminder_messages(result) == []

    def test_no_reminder_when_no_agents(self) -> None:
        # Background enabled but nothing dispatched -> never inject.
        result = _eval_deepagent(
            agent_kwargs={"background": True},
            outputs=[
                _idle(),
                _idle(),
                _idle(),
                _idle(),
                _idle(),
                _idle(),
                _submit("done"),
            ],
        )
        assert _reminder_messages(result) == []

    def test_no_reminder_when_disabled(self) -> None:
        # background=False installs no wrapper at all.
        result = _eval_deepagent(
            agent_kwargs={"background": False},
            outputs=[
                _idle(),
                _idle(),
                _idle(),
                _idle(),
                _idle(),
                _idle(),
                _submit("done"),
            ],
        )
        assert _reminder_messages(result) == []

    def test_composes_with_callable_on_continue(self) -> None:
        # A user-supplied on_continue is still invoked, and the reminder
        # rides along on top of it.
        from inspect_ai.agent._agent import AgentState

        calls = {"n": 0}

        async def my_continue(state: AgentState) -> bool:
            calls["n"] += 1
            return True

        bg_run = _build_blocking_subagent("run_one")
        result = _eval_deepagent(
            agent_kwargs={"subagents": [bg_run], "on_continue": my_continue},
            outputs=[
                _agent_call("run_one"),
                _idle(),
                _idle(),
                _idle(),
                _idle(),
                _idle(),
                _submit("done"),
            ],
        )
        assert calls["n"] >= 5
        assert len(_reminder_messages(result)) >= 1

    def test_composes_with_str_on_continue(self) -> None:
        # A str on_continue is injected on idle (stop) turns; when a reminder
        # is due it is appended to that string (same user message).
        bg_run = _build_blocking_subagent("run_one")
        result = _eval_deepagent(
            agent_kwargs={
                "subagents": [bg_run],
                "on_continue": "Carry on with the plan.",
            },
            outputs=[
                _agent_call("run_one"),
                _idle(),
                _idle(),
                _idle(),
                _idle(),
                _idle(),
                _submit("done"),
            ],
        )
        from inspect_ai.model._chat_message import ChatMessageUser

        user_texts = [
            m.text for m in result["messages"] if isinstance(m, ChatMessageUser)
        ]
        # the custom continue string is used on idle turns
        assert any("Carry on with the plan." in t for t in user_texts)
        # the reminder rides along in the same message it is appended to
        combined = [
            t
            for t in user_texts
            if "Carry on with the plan." in t and "Automatic reminder" in t
        ]
        assert len(combined) >= 1
