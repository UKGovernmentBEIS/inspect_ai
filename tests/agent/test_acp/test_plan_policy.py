"""Phase 10 unit tests for the AgentPlanUpdate policy.

Tests the pure helpers + per-connection forwarder transformation
that converts ``update_plan`` / ``todo_write`` tool-call notifications
into ACP ``AgentPlanUpdate`` notifications for plan-capable clients.

No socket needed — these poke the methods on a bare
``ConnectionHandler`` instance.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from acp.helpers import (
    session_notification,
    start_tool_call,
    text_block,
    update_agent_message,
    update_tool_call,
)
from acp.schema import AgentPlanUpdate

from inspect_ai.agent._acp.connection import (
    PLAN_RENDERING_META_KEY,
    Bound,
    ConnectionHandler,
)
from inspect_ai.agent._acp.session_router import PLAN_TOOL_NAMES, Forwarders

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _handler() -> ConnectionHandler:
    """Fresh handler bound to a synthetic wire session (needed by translators)."""
    h = ConnectionHandler()
    h.state.binding = Bound(
        wire_session_id="wire-session", target_session_id="wire-session"
    )
    return h


def _forwarders(*, client_renders_plan: bool = False) -> Forwarders:
    """Fresh Forwarders for plan-policy transform tests.

    Uses a bare handler for the ConnectionState ref + as the approver
    client placeholder; MagicMock for the Connection (transform tests
    never call ``send_notification``).
    """
    h = _handler()
    h.state.client_renders_plan = client_renders_plan
    return Forwarders(h.state, MagicMock(), h)


def _client_info(name: str) -> Any:
    """Stub a minimal ACP `Implementation` model for `client_info`."""
    info = MagicMock()
    info.name = name
    return info


def _client_capabilities(meta: dict[str, Any] | None = None) -> Any:
    """Stub a minimal ACP `ClientCapabilities` with optional `_meta` payload."""
    caps = MagicMock()
    caps.field_meta = meta
    return caps


# ---------------------------------------------------------------------------
# Capability detection at initialize()
# ---------------------------------------------------------------------------


async def test_zed_client_name_flags_plan_rendering() -> None:
    """`client_info.name == "zed"` flips client_renders_plan to True."""
    h = _handler()
    await h.initialize(
        protocol_version=1,
        client_capabilities=_client_capabilities(),
        client_info=_client_info("zed"),
    )
    assert h.state.client_renders_plan is True


async def test_toad_client_name_flags_plan_rendering() -> None:
    """Both names in the allowlist flip the flag."""
    h = _handler()
    await h.initialize(
        protocol_version=1,
        client_capabilities=_client_capabilities(),
        client_info=_client_info("toad"),
    )
    assert h.state.client_renders_plan is True


async def test_client_name_match_is_case_insensitive() -> None:
    """Allowlist match is case-insensitive (Zed sends 'Zed', spec-wise)."""
    h = _handler()
    await h.initialize(
        protocol_version=1,
        client_capabilities=_client_capabilities(),
        client_info=_client_info("ZED"),
    )
    assert h.state.client_renders_plan is True


async def test_unknown_client_with_meta_optin_flags_plan_rendering() -> None:
    """`_meta[inspect.plan_rendering] = true` overrides the allowlist."""
    h = _handler()
    await h.initialize(
        protocol_version=1,
        client_capabilities=_client_capabilities({PLAN_RENDERING_META_KEY: True}),
        client_info=_client_info("custom-client"),
    )
    assert h.state.client_renders_plan is True


async def test_unknown_client_without_meta_does_not_flag() -> None:
    """Default-off: unknown client name AND no _meta opt-in → False."""
    h = _handler()
    await h.initialize(
        protocol_version=1,
        client_capabilities=_client_capabilities(),
        client_info=_client_info("some-other-editor"),
    )
    assert h.state.client_renders_plan is False


async def test_missing_client_info_and_meta_does_not_flag() -> None:
    """No client_info AND no client_capabilities → False (safe default)."""
    h = _handler()
    await h.initialize(protocol_version=1, client_capabilities=None, client_info=None)
    assert h.state.client_renders_plan is False


async def test_raw_events_opt_in() -> None:
    """`_meta[inspect.raw_events] = true` flips raw_events_enabled."""
    h = _handler()
    await h.initialize(
        protocol_version=1,
        client_capabilities=_client_capabilities({"inspect.raw_events": True}),
        client_info=None,
    )
    assert h.state.raw_events_enabled is True


async def test_raw_events_default_off() -> None:
    """Without the _meta opt-in, raw events stay off."""
    h = _handler()
    await h.initialize(
        protocol_version=1,
        client_capabilities=_client_capabilities(),
        client_info=_client_info("zed"),
    )
    # zed flips the plan flag but NOT the raw flag.
    assert h.state.raw_events_enabled is False


# ---------------------------------------------------------------------------
# _build_plan_update — translation
# ---------------------------------------------------------------------------


def test_build_plan_update_translates_update_plan() -> None:
    """update_plan's {plan: [{step, status}, ...]} → AgentPlanUpdate entries."""
    f = _forwarders()
    raw_input = {
        "plan": [
            {"step": "Analyze the requirements", "status": "completed"},
            {"step": "Write the code", "status": "in_progress"},
            {"step": "Run tests", "status": "pending"},
        ]
    }
    notif = f._build_plan_update("update_plan", raw_input)
    assert notif is not None
    assert notif.session_id == "wire-session"
    assert isinstance(notif.update, AgentPlanUpdate)
    assert len(notif.update.entries) == 3
    assert notif.update.entries[0].content == "Analyze the requirements"
    assert notif.update.entries[0].status == "completed"
    assert notif.update.entries[0].priority == "medium"
    assert notif.update.entries[1].content == "Write the code"
    assert notif.update.entries[1].status == "in_progress"
    assert notif.update.entries[2].status == "pending"


def test_build_plan_update_translates_todo_write() -> None:
    """todo_write's {todos: [{content, status}, ...]} → AgentPlanUpdate entries."""
    f = _forwarders()
    raw_input = {
        "todos": [
            {"content": "Set up CI", "status": "in_progress"},
            {"content": "Write docs", "status": "pending"},
        ]
    }
    notif = f._build_plan_update("todo_write", raw_input)
    assert notif is not None
    assert isinstance(notif.update, AgentPlanUpdate)
    assert [e.content for e in notif.update.entries] == [
        "Set up CI",
        "Write docs",
    ]
    assert [e.status for e in notif.update.entries] == ["in_progress", "pending"]
    # priority defaulted to medium.
    assert all(e.priority == "medium" for e in notif.update.entries)


def test_build_plan_update_returns_none_for_unknown_title() -> None:
    """A title that isn't a plan tool returns None (caller passes through)."""
    f = _forwarders()
    assert f._build_plan_update("some_other_tool", {"plan": []}) is None


def test_build_plan_update_returns_none_for_missing_items_list() -> None:
    """Malformed raw_input (no plan/todos list) returns None."""
    f = _forwarders()
    assert f._build_plan_update("update_plan", {}) is None
    assert f._build_plan_update("todo_write", {"plan": []}) is None  # wrong key


def test_build_plan_update_returns_none_for_non_dict_raw_input() -> None:
    """raw_input must be a dict; otherwise return None."""
    f = _forwarders()
    assert f._build_plan_update("update_plan", None) is None
    assert f._build_plan_update("update_plan", "garbage") is None


def test_build_plan_update_handles_partial_item_dicts() -> None:
    """Items missing fields default sensibly (status="pending", content="")."""
    f = _forwarders()
    notif = f._build_plan_update("update_plan", {"plan": [{}, {"step": "x"}]})
    assert notif is not None
    assert isinstance(notif.update, AgentPlanUpdate)
    assert notif.update.entries[0].content == ""
    assert notif.update.entries[0].status == "pending"
    assert notif.update.entries[1].content == "x"


def test_build_plan_update_skips_non_dict_items() -> None:
    """Items that aren't dicts are silently skipped."""
    f = _forwarders()
    notif = f._build_plan_update(
        "update_plan", {"plan": [{"step": "a", "status": "pending"}, "junk", 42]}
    )
    assert notif is not None
    assert isinstance(notif.update, AgentPlanUpdate)
    assert len(notif.update.entries) == 1
    assert notif.update.entries[0].content == "a"


# ---------------------------------------------------------------------------
# _maybe_transform_plan_tool — forwarder behavior
# ---------------------------------------------------------------------------


def _start(tool_id: str, title: str, status: Any, raw_input: Any = None) -> Any:
    return session_notification(
        "wire-session",
        start_tool_call(
            tool_call_id=tool_id, title=title, status=status, raw_input=raw_input
        ),
    )


def _progress(tool_id: str, status: Any) -> Any:
    return session_notification(
        "wire-session",
        update_tool_call(tool_call_id=tool_id, status=status),
    )


def test_non_plan_capable_client_passthrough() -> None:
    """Without client_renders_plan, every notification passes through."""
    f = _forwarders(client_renders_plan=False)
    notif = _start("tc1", "update_plan", "completed", {"plan": [{"step": "x"}]})
    assert f._maybe_transform_plan_tool(notif) is notif


def test_plan_capable_in_progress_start_is_suppressed() -> None:
    """Plan-capable + in_progress plan-tool start → suppress (return None)."""
    f = _forwarders(client_renders_plan=True)
    notif = _start(
        "tc1", "update_plan", "in_progress", {"plan": [{"step": "x", "status": "p"}]}
    )
    assert f._maybe_transform_plan_tool(notif) is None
    # Tool is stashed for later progress notification.
    assert "tc1" in f._plan_tool_stash


def test_plan_capable_completed_progress_emits_plan() -> None:
    """ToolCallProgress(completed) for stashed plan tool → AgentPlanUpdate."""
    f = _forwarders(client_renders_plan=True)
    # First, the start notification stashes raw_input.
    f._maybe_transform_plan_tool(
        _start(
            "tc1",
            "update_plan",
            "in_progress",
            {"plan": [{"step": "step-a", "status": "completed"}]},
        )
    )
    # Then progress arrives.
    out = f._maybe_transform_plan_tool(_progress("tc1", "completed"))
    assert out is not None
    assert isinstance(out.update, AgentPlanUpdate)
    assert out.update.entries[0].content == "step-a"
    # Stash cleared on emit.
    assert "tc1" not in f._plan_tool_stash


def test_plan_capable_instant_complete_start_emits_plan() -> None:
    """A plan-tool start that's already completed (instant) emits Plan directly."""
    f = _forwarders(client_renders_plan=True)
    notif = _start(
        "tc-instant",
        "update_plan",
        "completed",
        {"plan": [{"step": "fast", "status": "completed"}]},
    )
    out = f._maybe_transform_plan_tool(notif)
    assert out is not None
    assert isinstance(out.update, AgentPlanUpdate)
    assert out.update.entries[0].content == "fast"


def test_plan_capable_non_plan_tool_passthrough() -> None:
    """Plan-capable + non-plan-tool notification → passthrough."""
    f = _forwarders(client_renders_plan=True)
    notif = _start("tc-x", "bash", "completed", {"cmd": "ls"})
    assert f._maybe_transform_plan_tool(notif) is notif


def test_plan_capable_non_tool_notification_passthrough() -> None:
    """Plan-capable + agent_message_chunk (not a tool call) → passthrough."""
    f = _forwarders(client_renders_plan=True)
    notif = session_notification(
        "wire-session", update_agent_message(text_block("hello"))
    )
    assert f._maybe_transform_plan_tool(notif) is notif


def test_progress_without_stash_passes_through() -> None:
    """A progress notif for an untracked tool_call_id passes through."""
    f = _forwarders(client_renders_plan=True)
    # No prior start_tool_call → no stash.
    out = f._maybe_transform_plan_tool(_progress("tc-unknown", "completed"))
    # Passthrough (returns the same notif, not None).
    assert out is not None
    # Update kind is still ToolCallProgress, not AgentPlanUpdate.
    assert not isinstance(out.update, AgentPlanUpdate)


# ---------------------------------------------------------------------------
# Sanity: constants are what we documented
# ---------------------------------------------------------------------------


def test_plan_tool_names_constant() -> None:
    """The hard-coded plan-tool name allowlist is `{update_plan, todo_write}`."""
    assert PLAN_TOOL_NAMES == frozenset({"update_plan", "todo_write"})


@pytest.mark.parametrize("name", ["update_plan", "todo_write"])
def test_plan_tool_names_includes_inspect_first_party_planners(name: str) -> None:
    """Inspect's first-party planning tools are recognized."""
    assert name in PLAN_TOOL_NAMES
