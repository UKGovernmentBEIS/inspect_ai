"""Tests for AgentBridge._track_state main-thread tracking.

The bridge observes every generation a scaffold makes (main agent loop,
side calls like opencode's session title generation, sub-agent loops,
post-compaction continuations) and must surface the *main* conversation
as the agent state. See meridianlabs-ai/inspect_ai#140 for the failure
mode where a longer side call permanently displaced the real conversation.
"""

from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._model_output import ModelOutput

TASK = "In the year 2022, what castle did the Doctor spend 4.5 billion years in?"

TASK_SYSTEM = ChatMessageSystem(content="You are opencode, an agent that ...")


def task_bridge() -> AgentBridge:
    return AgentBridge(AgentState(messages=[ChatMessageUser(content=TASK)]))


async def track(
    bridge: AgentBridge, input: list[ChatMessage], completion: str
) -> ModelOutput:
    output = ModelOutput.from_content(model="mockllm/model", content=completion)
    await bridge._track_state(input, output)
    return output


def title_generation_input() -> list[ChatMessage]:
    # mirrors opencode's session title generation request: its own system
    # prompt, a "Generate a title" preamble, then the first user message
    return [
        ChatMessageSystem(content="You are a title generator ..."),
        ChatMessageUser(content="Generate a title for this conversation:\n"),
        ChatMessageUser(content=TASK),
    ]


# ---------------------------------------------------------------------------
# Reproduction of meridianlabs-ai/inspect_ai#140
# ---------------------------------------------------------------------------


async def test_side_call_arriving_first_does_not_displace_task_thread() -> None:
    """A longer side call that lands before the main loop must not win.

    opencode fires a 4-message title-generation call before the (3-message,
    single-turn) task call; the task thread descends from the agent's input
    while the title thread does not, so the task thread must be tracked.
    """
    bridge = task_bridge()

    await track(bridge, title_generation_input(), "Doctor Who Series 9 setting")

    # the real task call (single turn agent loop)
    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=TASK)], "Castle")

    # a subsequent same-length one-shot task call must not displace the answer
    await track(
        bridge,
        [TASK_SYSTEM, ChatMessageUser(content=TASK)],
        "Castle TARDIS Console Room",
    )

    assert bridge.state.output.completion == "Castle"
    assert [m.text for m in bridge.state.messages] == [
        TASK_SYSTEM.text,
        TASK,
        "Castle",
    ]


async def test_side_call_after_main_loop_does_not_displace_task_thread() -> None:
    """A longer side call must not displace an established main loop."""
    bridge = task_bridge()

    # two-turn main loop
    turn1: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    out1 = await track(bridge, turn1, "let me look into that")
    turn2 = turn1 + [out1.message, ChatMessageTool(content="tool result")]
    await track(bridge, turn2, "Castle")

    # longer unrelated side call (would win under a pure length heuristic)
    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a title generator ..."),
            ChatMessageUser(content="Generate a title for this conversation:\n"),
            ChatMessageUser(content=TASK),
            ChatMessageUser(content="Respond with the title only."),
            ChatMessageUser(content="Do not use quotes."),
        ],
        "Doctor Who Series 9 setting",
    )

    assert bridge.state.output.completion == "Castle"
    assert len(bridge.state.messages) == len(turn2) + 1


# ---------------------------------------------------------------------------
# Regression: behaviors the previous heuristic already supported
# ---------------------------------------------------------------------------


async def test_main_loop_accumulation_is_tracked() -> None:
    bridge = task_bridge()

    turn1: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    out1 = await track(bridge, turn1, "checking")
    assert bridge.state.output.completion == "checking"

    turn2 = turn1 + [out1.message, ChatMessageTool(content="tool result")]
    out2 = await track(bridge, turn2, "still checking")
    assert bridge.state.output.completion == "still checking"

    turn3 = turn2 + [out2.message, ChatMessageTool(content="tool result 2")]
    await track(bridge, turn3, "Castle")
    assert bridge.state.output.completion == "Castle"
    assert len(bridge.state.messages) == len(turn3) + 1


async def test_shorter_side_call_is_ignored() -> None:
    # e.g. claude code's bash path detection side call
    bridge = task_bridge()

    turn1: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    out1 = await track(bridge, turn1, "working")
    turn2 = turn1 + [out1.message, ChatMessageTool(content="tool result")]
    out2 = await track(bridge, turn2, "more work")

    await track(
        bridge,
        [ChatMessageUser(content="Detect the paths in this bash command: ls /tmp")],
        "/tmp",
    )
    assert bridge.state.output.completion == "more work"

    # main loop continues to be tracked afterwards
    turn3 = turn2 + [out2.message, ChatMessageTool(content="tool result 2")]
    await track(bridge, turn3, "Castle")
    assert bridge.state.output.completion == "Castle"


async def test_scaffold_compaction_recovery() -> None:
    """After the scaffold compacts its history the new (shorter) loop wins."""
    bridge = task_bridge()

    # main loop accumulates
    turn1: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    out1 = await track(bridge, turn1, "working")
    turn2 = turn1 + [out1.message, ChatMessageTool(content="tool result")]
    out2 = await track(bridge, turn2, "more work")
    turn3 = turn2 + [out2.message, ChatMessageTool(content="tool result 2")]
    await track(bridge, turn3, "even more work")

    # compaction: history replaced by a summary (no longer shares the
    # original input prefix), then the loop keeps appending
    compact1: list[ChatMessage] = [
        TASK_SYSTEM,
        ChatMessageUser(content="Summary of the conversation so far: ..."),
    ]
    cout1 = await track(bridge, compact1, "compacted work")
    compact2 = compact1 + [cout1.message, ChatMessageTool(content="tool result 3")]
    await track(bridge, compact2, "Castle")

    assert bridge.state.output.completion == "Castle"
    assert len(bridge.state.messages) == len(compact2) + 1


async def test_length_heuristic_fallback_without_initial_input() -> None:
    # with no initial input to anchor descent, accumulation still tracks
    bridge = AgentBridge(AgentState(messages=[]))

    turn1: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    out1 = await track(bridge, turn1, "working")
    turn2 = turn1 + [out1.message, ChatMessageTool(content="tool result")]
    await track(bridge, turn2, "Castle")
    assert bridge.state.output.completion == "Castle"

    # shorter side call ignored
    await track(bridge, [ChatMessageUser(content="side call")], "side answer")
    assert bridge.state.output.completion == "Castle"


# ---------------------------------------------------------------------------
# Additional thread-tracking behaviors
# ---------------------------------------------------------------------------


async def test_repeated_same_length_call_keeps_first_answer() -> None:
    # a second one-shot call with the same input does not displace the answer
    bridge = task_bridge()
    input: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    await track(bridge, input, "Castle")
    await track(bridge, input, "Castle TARDIS Console Room")
    assert bridge.state.output.completion == "Castle"


async def test_sub_agent_loop_recovers_to_main_thread() -> None:
    """The main loop reclaims tracking after a sub-agent loop runs."""
    bridge = task_bridge()

    # establish main loop
    turn1: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    out1 = await track(bridge, turn1, "delegating")
    turn2 = turn1 + [out1.message, ChatMessageTool(content="tool result")]
    out2 = await track(bridge, turn2, "spawning subtask")

    # sub-agent loop (its own conversation, multiple calls)
    sub1: list[ChatMessage] = [
        ChatMessageSystem(content="You are a subtask agent ..."),
        ChatMessageUser(content="Research Doctor Who series 9 filming locations."),
    ]
    sout1 = await track(bridge, sub1, "researching")
    sub2 = sub1 + [sout1.message, ChatMessageTool(content="search results")]
    await track(bridge, sub2, "Cardiff Castle")

    # main loop resumes and keeps appending
    turn3 = turn2 + [out2.message, ChatMessageTool(content="subtask: Cardiff Castle")]
    tout3 = await track(bridge, turn3, "almost there")
    turn4 = turn3 + [tout3.message, ChatMessageTool(content="tool result 2")]
    await track(bridge, turn4, "Castle")

    assert bridge.state.output.completion == "Castle"
    assert len(bridge.state.messages) == len(turn4) + 1
