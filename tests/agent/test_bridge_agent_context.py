"""Tests for the ambient agent bridge context (AgentBridgeContext)."""

import anyio

from inspect_ai.agent._bridge.context import (
    AgentBridgeContext,
    bridged_request_scope,
    current_agent_bridge_context,
    current_bridge_request,
    is_sub_agent,
    set_agent_bridge_context,
)


def test_no_context_outside_bridged_request() -> None:
    assert current_agent_bridge_context() is None
    assert current_bridge_request() is None
    assert is_sub_agent() is False


def test_scope_stamps_default_unknown() -> None:
    with bridged_request_scope("some-slug"):
        context = current_agent_bridge_context()
        assert context == AgentBridgeContext("unknown", "inferred")
        assert context is not None and context.is_root is False
        request = current_bridge_request()
        assert request is not None and request.model == "some-slug"
    # reset on exit — no leakage into the enclosing context
    assert current_agent_bridge_context() is None
    assert current_bridge_request() is None


def test_scope_without_requested_model() -> None:
    with bridged_request_scope(None):
        assert current_agent_bridge_context() == AgentBridgeContext(
            "unknown", "inferred"
        )
        assert current_bridge_request() is None


def test_set_agent_bridge_context_within_scope() -> None:
    with bridged_request_scope("slug"):
        set_agent_bridge_context(AgentBridgeContext("subagent", "structural"))
        assert is_sub_agent() is True
        context = current_agent_bridge_context()
        assert context is not None
        assert context.kind == "subagent"
        assert context.certainty == "structural"
    # the scope's finally bounds the setter too
    assert current_agent_bridge_context() is None


def test_is_sub_agent_only_for_subagent_kind() -> None:
    expectations = [
        ("root", False),
        ("subagent", True),
        ("utility", False),
        ("unknown", False),
    ]
    for kind, expected in expectations:
        with bridged_request_scope(None):
            set_agent_bridge_context(AgentBridgeContext(kind, "structural"))  # type: ignore[arg-type]
            assert is_sub_agent() is expected, f"kind={kind}"


def test_is_root_property() -> None:
    assert AgentBridgeContext("root", "structural").is_root is True
    assert AgentBridgeContext("subagent", "structural").is_root is False
    assert AgentBridgeContext("utility", "inferred").is_root is False
    assert AgentBridgeContext("unknown", "inferred").is_root is False


async def test_concurrent_tasks_have_isolated_contexts() -> None:
    observed: dict[str, str | None] = {}

    async def worker(name: str, kind: str) -> None:
        with bridged_request_scope(f"{name}-slug"):
            set_agent_bridge_context(AgentBridgeContext(kind, "structural"))  # type: ignore[arg-type]
            await anyio.sleep(0.01)  # force interleaving
            context = current_agent_bridge_context()
            request = current_bridge_request()
            observed[name] = context.kind if context else None
            observed[f"{name}-model"] = request.model if request else None

    async with anyio.create_task_group() as tg:
        tg.start_soon(worker, "a", "root")
        tg.start_soon(worker, "b", "subagent")

    assert observed["a"] == "root"
    assert observed["b"] == "subagent"
    assert observed["a-model"] == "a-slug"
    assert observed["b-model"] == "b-slug"
