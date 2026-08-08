"""Tests for the ambient agent bridge context (AgentBridgeContext)."""

from typing import Any

import anyio
import pytest

from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.anthropic_api_impl import (
    inspect_anthropic_api_request_impl,
)
from inspect_ai.agent._bridge.context import (
    AgentBridgeContext,
    BridgeRequest,
    agent_bridge_context_scope,
    bridged_request_scope,
    current_agent_bridge_context,
    current_bridge_request,
    is_root_agent,
    is_sub_agent,
    set_agent_bridge_context,
)
from inspect_ai.agent._bridge.google_api_impl import inspect_google_api_request_impl
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import (
    bridge_generate,
    default_code_execution_providers,
    internal_web_search_providers,
)
from inspect_ai.event._model import ModelEvent
from inspect_ai.model import GenerateConfig, Model, ModelOutput, get_model
from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo


def test_no_context_outside_bridged_request() -> None:
    assert current_agent_bridge_context() is None
    assert current_bridge_request() is None
    assert is_sub_agent() is False


def test_scope_stamps_default_unknown() -> None:
    with bridged_request_scope("some-slug"):
        context = current_agent_bridge_context()
        assert context == AgentBridgeContext("unknown")
        request = current_bridge_request()
        assert request is not None and request.model == "some-slug"
    # reset on exit — no leakage into the enclosing context
    assert current_agent_bridge_context() is None
    assert current_bridge_request() is None


def test_scope_without_requested_model() -> None:
    with bridged_request_scope(None):
        assert current_agent_bridge_context() == AgentBridgeContext("unknown")
        assert current_bridge_request() is None


def test_set_agent_bridge_context_within_scope() -> None:
    with bridged_request_scope("slug"):
        set_agent_bridge_context(AgentBridgeContext("subagent"))
        assert is_sub_agent() is True
        context = current_agent_bridge_context()
        assert context is not None
        assert context.kind == "subagent"
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
            set_agent_bridge_context(AgentBridgeContext(kind))  # type: ignore[arg-type]
            assert is_sub_agent() is expected, f"kind={kind}"


def test_is_root_agent_semantics() -> None:
    # permissive gate: treat as root outside bridged requests...
    assert is_root_agent() is True
    with bridged_request_scope(None):
        # ...and when attribution is unknown (the unset default)
        assert is_root_agent() is True
    expectations = [
        ("root", True),
        ("subagent", False),
        ("utility", False),
        ("unknown", True),
    ]
    for kind, expected in expectations:
        with bridged_request_scope(None):
            set_agent_bridge_context(AgentBridgeContext(kind))  # type: ignore[arg-type]
            assert is_root_agent() is expected, f"kind={kind}"


async def test_concurrent_tasks_have_isolated_contexts() -> None:
    observed: dict[str, str | None] = {}

    async def worker(name: str, kind: str) -> None:
        with bridged_request_scope(f"{name}-slug"):
            set_agent_bridge_context(AgentBridgeContext(kind))  # type: ignore[arg-type]
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


# --- bridge_generate integration -------------------------------------------


async def test_bridge_generate_stamps_default_and_slug() -> None:
    seen: dict[str, Any] = {}

    async def capture_filter(
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> None:
        seen["context"] = current_agent_bridge_context()
        seen["request"] = current_bridge_request()
        return None

    bridge = AgentBridge(state=AgentState(messages=[]), filter=capture_filter)
    await bridge_generate(
        bridge,
        get_model("mockllm/model"),
        [ChatMessageUser(content="hi")],
        [],
        None,
        GenerateConfig(),
        requested_model="scaffold-slug",
    )
    assert seen["context"] == AgentBridgeContext("unknown")
    assert seen["request"] == BridgeRequest(model="scaffold-slug")
    # scope reset after the request completes
    assert current_agent_bridge_context() is None
    assert current_bridge_request() is None


async def test_filter_set_context_visible_downstream_in_sink() -> None:
    """A context set at filter time is visible inside model.generate (sink)."""
    seen: dict[str, Any] = {}

    async def marking_filter(
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> None:
        set_agent_bridge_context(AgentBridgeContext("subagent"))
        return None

    class CaptureSink:
        def on_pending(self, event: ModelEvent) -> None:
            seen["pending_is_sub_agent"] = is_sub_agent()

        def on_complete(self, event: ModelEvent) -> None:
            seen["complete_context"] = current_agent_bridge_context()

    bridge = AgentBridge(
        state=AgentState(messages=[]),
        filter=marking_filter,
        model_event_sink=CaptureSink(),
    )
    await bridge_generate(
        bridge,
        get_model("mockllm/model"),
        [ChatMessageUser(content="hi")],
        [],
        None,
        GenerateConfig(),
        requested_model="scaffold-slug",
    )
    assert seen["pending_is_sub_agent"] is True
    assert seen["complete_context"] == AgentBridgeContext("subagent")
    assert current_agent_bridge_context() is None


async def test_bridge_generate_without_requested_model() -> None:
    seen: dict[str, Any] = {}

    async def capture_filter(
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> None:
        seen["context"] = current_agent_bridge_context()
        seen["request"] = current_bridge_request()
        return None

    bridge = AgentBridge(state=AgentState(messages=[]), filter=capture_filter)
    await bridge_generate(
        bridge,
        get_model("mockllm/model"),
        [ChatMessageUser(content="hi")],
        [],
        None,
        GenerateConfig(),
    )
    assert seen["context"] == AgentBridgeContext("unknown")
    assert seen["request"] is None


# --- impl passthrough -------------------------------------------------------


async def test_anthropic_impl_passes_requested_slug() -> None:
    seen: dict[str, Any] = {}

    async def capture_filter(
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> None:
        seen["request"] = current_bridge_request()
        return None

    bridge = AgentBridge(
        state=AgentState(messages=[]),
        filter=capture_filter,
        model="mockllm/model",
    )
    json_data = {
        "model": "claude-sub-agent-slug",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "hi"}],
    }
    await inspect_anthropic_api_request_impl(
        json_data,
        None,
        internal_web_search_providers(),
        default_code_execution_providers(),
        bridge,
    )
    # the raw scaffold slug survives even though the model resolved elsewhere
    assert seen["request"] == BridgeRequest(model="claude-sub-agent-slug")


async def test_google_impl_reports_no_request_when_model_omitted() -> None:
    """A Google scaffold that omits `model` must not fabricate a slug.

    `bridge_model_name` still falls back to "inspect" for model *resolution*
    (there's a model to run either way), but `current_bridge_request()` must
    report None -- there was no scaffold-requested slug to record.
    """
    seen: dict[str, Any] = {}

    async def capture_filter(
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> None:
        seen["request"] = current_bridge_request()
        return None

    bridge = AgentBridge(
        state=AgentState(messages=[]),
        filter=capture_filter,
        model="mockllm/model",
    )
    json_data = {
        # no "model" key -- scaffold never requested a slug
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
    }
    await inspect_google_api_request_impl(
        json_data,
        internal_web_search_providers(),
        default_code_execution_providers(),
        bridge,
    )
    assert seen["request"] is None


# --- public exports ----------------------------------------------------------


def test_public_exports() -> None:
    from inspect_ai.agent import (
        AgentBridgeContext as PublicContext,
    )
    from inspect_ai.agent import (
        BridgeRequest as PublicRequest,
    )
    from inspect_ai.agent import (
        current_agent_bridge_context as public_current,
    )
    from inspect_ai.agent import (
        current_bridge_request as public_request,
    )
    from inspect_ai.agent import (
        is_root_agent as public_is_root_agent,
    )
    from inspect_ai.agent import (
        is_sub_agent as public_is_sub_agent,
    )
    from inspect_ai.agent import (
        set_agent_bridge_context as public_set,
    )

    assert PublicContext is AgentBridgeContext
    assert PublicRequest is BridgeRequest
    assert public_current is current_agent_bridge_context
    assert public_request is current_bridge_request
    assert public_is_sub_agent is is_sub_agent
    assert public_is_root_agent is is_root_agent
    assert public_set is set_agent_bridge_context


# --- final-review fixes ------------------------------------------------------


def test_nested_scopes_restore_outer() -> None:
    """A nested `agent_bridge_context_scope` restores the enclosing value on exit."""
    with bridged_request_scope("slug"):  # scope A: defaults to "unknown"
        set_agent_bridge_context(AgentBridgeContext("subagent"))
        assert current_agent_bridge_context() == AgentBridgeContext("subagent")
        with agent_bridge_context_scope(AgentBridgeContext("unknown")):  # scope B
            assert current_agent_bridge_context() == AgentBridgeContext("unknown")
        # exiting B restores the subagent value set within A
        assert current_agent_bridge_context() == AgentBridgeContext("subagent")
    # exiting A (the outermost scope) leaves no context at all
    assert current_agent_bridge_context() is None


async def test_filter_exception_resets_scope() -> None:
    """An exception raised by the filter propagates and still unwinds the scope."""

    async def raising_filter(
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> None:
        raise RuntimeError("filter blew up")

    bridge = AgentBridge(state=AgentState(messages=[]), filter=raising_filter)
    with pytest.raises(RuntimeError, match="filter blew up"):
        await bridge_generate(
            bridge,
            get_model("mockllm/model"),
            [ChatMessageUser(content="hi")],
            [],
            None,
            GenerateConfig(),
            requested_model="scaffold-slug",
        )
    assert current_agent_bridge_context() is None


async def test_retry_attempts_start_with_default_context() -> None:
    """A filter-set context from a refused attempt must not leak into the retry."""
    seen: dict[str, Any] = {}
    calls = {"n": 0}

    async def refuse_then_record_filter(
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | None:
        calls["n"] += 1
        if calls["n"] == 1:
            # first attempt: stamp a non-default context, then refuse
            set_agent_bridge_context(AgentBridgeContext("subagent"))
            return ModelOutput.from_content(
                model="mockllm/model",
                content="refused",
                stop_reason="content_filter",
            )
        else:
            # second attempt: record whether the context started clean
            seen["context"] = current_agent_bridge_context()
            return None

    bridge = AgentBridge(
        state=AgentState(messages=[]),
        filter=refuse_then_record_filter,
        retry_refusals=1,
    )
    await bridge_generate(
        bridge,
        get_model("mockllm/model"),
        [ChatMessageUser(content="hi")],
        [],
        None,
        GenerateConfig(),
        requested_model="scaffold-slug",
    )
    assert calls["n"] == 2
    assert seen["context"] == AgentBridgeContext("unknown")


def test_agent_bridge_context_scope_utility() -> None:
    """`agent_bridge_context_scope` stamps utility and restores the prior value.

    This stands in for `test_compaction_generates_read_utility`: wiring an
    actual `CompactionStrategy` into `bridge_generate` so its internal
    `model.generate()` call is observable requires the full `eval()` /
    transcript harness used by `test_agent_bridge_compaction.py` (an OpenAI
    client, a real compaction threshold crossing, etc.) -- heavy scaffolding
    for something `agent_bridge_context_scope` already guarantees on its own.
    Exercising the context manager directly covers the same guarantee that
    `_bridge_generate_impl` relies on when it wraps `compact.compact_input()`.
    """
    with bridged_request_scope("slug"):
        set_agent_bridge_context(AgentBridgeContext("subagent"))
        with agent_bridge_context_scope(AgentBridgeContext("utility")):
            assert current_agent_bridge_context() == AgentBridgeContext("utility")
        # prior value (set before entering the inner scope) is restored
        assert current_agent_bridge_context() == AgentBridgeContext("subagent")
    assert current_agent_bridge_context() is None


def test_setter_raises_outside_scope() -> None:
    with pytest.raises(RuntimeError):
        set_agent_bridge_context(AgentBridgeContext("root"))
