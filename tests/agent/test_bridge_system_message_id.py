"""Tests for stable ``ChatMessageSystem.id`` across system-prompt mutations.

Bridged scaffolds (Gemini CLI's plan-mode toggle, skill activation, etc.)
routinely mutate the system prompt mid-conversation. A pure content-hash
approach mints a fresh ``ChatMessageSystem.id`` every time, splitting the
downstream transcript tree into N parallel roots. The bridge treats the
system prompt as a single slot per conversation: same slot, same id,
regardless of content.
"""

from __future__ import annotations

from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import apply_message_ids
from inspect_ai.model._chat_message import ChatMessageSystem, ChatMessageUser


def _make_bridge() -> AgentBridge:
    return AgentBridge(state=AgentState(messages=[]))


def test_system_message_id_preserved_across_content_mutation() -> None:
    """The system message's id stays stable when its *content* changes."""
    bridge = _make_bridge()

    sys_v1 = ChatMessageSystem(content="You are a helpful assistant.")
    user_msg = ChatMessageUser(content="Hello")
    turn1_input: list = [sys_v1, user_msg]
    apply_message_ids(bridge, turn1_input)
    first_id = turn1_input[0].id
    assert first_id is not None

    # Turn 2: agent toggled plan mode. Same conversation, mutated system text.
    sys_v2 = ChatMessageSystem(
        content="You are a helpful assistant. (Plan mode active.)",
    )
    follow_up = ChatMessageUser(content="Plan it.")
    turn2_input: list = [sys_v2, user_msg, follow_up]
    apply_message_ids(bridge, turn2_input)

    assert turn2_input[0].id == first_id, (
        "mutated system prompt must keep the id from the first turn"
    )

    # Turn 3: content reverts (plan-mode off). Still the same slot.
    sys_v3 = ChatMessageSystem(content="You are a helpful assistant.")
    turn3_input: list = [sys_v3, user_msg, follow_up]
    apply_message_ids(bridge, turn3_input)

    assert turn3_input[0].id == first_id, (
        "reverted system prompt must keep the id from the first turn"
    )


def test_system_message_id_independent_per_bridge() -> None:
    """Each ``AgentBridge`` instance gets its own slot id."""
    bridge_a = _make_bridge()
    bridge_b = _make_bridge()

    sys = ChatMessageSystem(content="You are a helpful assistant.")

    apply_message_ids(bridge_a, [sys])
    a_id = sys.id

    sys.id = None
    apply_message_ids(bridge_b, [sys])
    b_id = sys.id

    assert a_id is not None and b_id is not None
    assert a_id != b_id, "two bridges must allocate independent system-message ids"
