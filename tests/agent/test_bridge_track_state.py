"""Tests for AgentBridge._track_state main-thread tracking.

The bridge observes every generation a scaffold makes (main agent loop,
side calls like opencode's session title generation, sub-agent loops,
post-compaction continuations) and must surface the *main* conversation
as the agent state. See meridianlabs-ai/inspect_ai#140 for the failure
mode where a longer side call permanently displaced the real conversation.
"""

from typing import Any

from test_helpers.checkpoint import RecordingCheckpointer

from inspect_ai._util.hash import mm3_hash
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.anthropic_api import inspect_anthropic_api_request
from inspect_ai.agent._bridge.completions import inspect_completions_api_request
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import (
    default_code_execution_providers,
    internal_web_search_providers,
)
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._model import Model, get_model
from inspect_ai.model._model_output import ModelOutput, ModelUsage

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


async def test_stray_descending_one_shot_does_not_displace_established_thread() -> None:
    """A short stray descending one-shot can't displace an established thread.

    The displacement gate's length arm compares against the tracked thread,
    not the previous call: a short intervening side call must not re-open the
    displacement window for a stray descending one-shot (e.g. a topic-detection
    call that re-sends the original user message under its own system prompt).
    """
    bridge = task_bridge()

    # main loop, then scaffold compaction: the compacted loop is promoted, so
    # the tracked thread is non-descending with multiple calls
    turn1: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    out1 = await track(bridge, turn1, "working")
    turn2 = turn1 + [out1.message, ChatMessageTool(content="tool result")]
    await track(bridge, turn2, "more work")

    compact1: list[ChatMessage] = [
        TASK_SYSTEM,
        ChatMessageUser(content="Summary of the conversation so far: ..."),
    ]
    cout1 = await track(bridge, compact1, "compacted work")
    compact2 = compact1 + [cout1.message, ChatMessageTool(content="tool result 2")]
    await track(bridge, compact2, "Castle")

    # short side call is parked (and lowers the previous-call message count)
    await track(
        bridge,
        [ChatMessageUser(content="Detect the paths in this bash command: ls /tmp")],
        "/tmp",
    )

    # stray descending one-shot: longer than the side call but shorter than
    # the tracked thread, so it must not displace the real conversation
    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a topic detector ..."),
            ChatMessageUser(content=TASK),
        ],
        "Doctor Who",
    )

    assert bridge.state.output.completion == "Castle"
    assert len(bridge.state.messages) == len(compact2) + 1


async def test_stray_descending_one_shot_does_not_displace_descending_thread() -> None:
    """Same lowered-bar guard for a *descending* tracked thread.

    With an intact (descending) main loop, a stray descending one-shot lands
    in the equal-verdict legacy arm; that arm must compare against the tracked
    thread, not the previous call, so a short intervening side call can't
    re-open the displacement window.
    """
    bridge = task_bridge()

    # intact main loop runs to its final answer (tracked thread descending)
    turn1: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    out1 = await track(bridge, turn1, "working")
    turn2 = turn1 + [out1.message, ChatMessageTool(content="tool result")]
    await track(bridge, turn2, "Castle")

    # short side call is parked (and lowers the previous-call message count)
    await track(
        bridge,
        [ChatMessageUser(content="Detect the paths in this bash command: ls /tmp")],
        "/tmp",
    )

    # stray descending one-shot: longer than the side call but shorter than
    # the tracked thread, so it must not displace the real conversation
    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a topic detector ..."),
            ChatMessageUser(content=TASK),
        ],
        "Doctor Who",
    )

    assert bridge.state.output.completion == "Castle"
    assert len(bridge.state.messages) == len(turn2) + 1


async def test_single_final_call_reclaims_main_thread_after_sub_agent_loop() -> None:
    """One final main-loop call reclaims tracking from a promoted sub-agent loop.

    A multi-call sub-agent loop takes over tracking via candidate promotion;
    when the main loop then resumes with exactly *one* further (longer) call,
    nothing will ever extend it, so it must displace the sub-agent thread
    directly rather than being parked as a candidate.
    """
    bridge = task_bridge()

    # establish main loop
    turn1: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    out1 = await track(bridge, turn1, "delegating")
    turn2 = turn1 + [out1.message, ChatMessageTool(content="tool result")]
    out2 = await track(bridge, turn2, "spawning subtask")
    turn3 = turn2 + [out2.message, ChatMessageTool(content="tool result 2")]
    out3 = await track(bridge, turn3, "waiting on subtask")

    # sub-agent loop (its own conversation, multiple calls -> promoted)
    sub1: list[ChatMessage] = [
        ChatMessageSystem(content="You are a subtask agent ..."),
        ChatMessageUser(content="Research Doctor Who series 9 filming locations."),
    ]
    sout1 = await track(bridge, sub1, "researching")
    sub2 = sub1 + [sout1.message, ChatMessageTool(content="search results")]
    await track(bridge, sub2, "Cardiff Castle")

    # main loop resumes with exactly one final call and stops
    turn4 = turn3 + [out3.message, ChatMessageTool(content="subtask: Cardiff Castle")]
    await track(bridge, turn4, "Castle")

    assert bridge.state.output.completion == "Castle"
    assert len(bridge.state.messages) == len(turn4) + 1


# ---------------------------------------------------------------------------
# Fingerprint robustness
# ---------------------------------------------------------------------------


async def test_extension_recognized_despite_new_ids_and_metadata() -> None:
    """Thread continuity must survive the scaffold's conversation store.

    Messages round-trip through the scaffold's own store between calls, so
    successive requests carry freshly-constructed message objects: new ids,
    different metadata. Only role + text are stable, and extension detection
    must key on exactly that.
    """
    bridge = task_bridge()

    turn1: list[ChatMessage] = [
        ChatMessageSystem(content="You are opencode, an agent that ...", id="sys-1"),
        ChatMessageUser(content=TASK, id="user-1", metadata={"turn": 1}),
    ]
    out1 = await track(bridge, turn1, "working")

    # the scaffold re-creates every message: different ids and metadata, and
    # the assistant echo is rebuilt from text rather than reusing out1.message
    turn2: list[ChatMessage] = [
        ChatMessageSystem(content="You are opencode, an agent that ...", id="sys-2"),
        ChatMessageUser(content=TASK, id="user-2", metadata={"turn": 2}),
        ChatMessageAssistant(content=out1.message.text, metadata={"replayed": True}),
        ChatMessageTool(content="tool result"),
    ]
    await track(bridge, turn2, "Castle")

    assert bridge.state.output.completion == "Castle"
    assert len(bridge.state.messages) == len(turn2) + 1


# ---------------------------------------------------------------------------
# Descent anchoring on the initial input
# ---------------------------------------------------------------------------


async def test_descent_anchor_ignores_system_prompt_replacement() -> None:
    """Descent anchors on the initial input's non-system messages.

    An agent state that starts with its own system prompt still anchors
    descent on the user input: the scaffold substitutes its own system prompt,
    and the task thread must still displace an earlier title call.
    """
    bridge = AgentBridge(
        AgentState(
            messages=[
                ChatMessageSystem(content="You are a helpful assistant."),
                ChatMessageUser(content=TASK),
            ]
        )
    )

    await track(bridge, title_generation_input(), "Doctor Who Series 9 setting")

    # scaffold runs the task under its own (different) system prompt
    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=TASK)], "Castle")

    assert bridge.state.output.completion == "Castle"
    assert [m.text for m in bridge.state.messages] == [
        TASK_SYSTEM.text,
        TASK,
        "Castle",
    ]


async def test_multi_message_initial_input_anchors_descent() -> None:
    """A multi-message input anchors descent on all of its non-system messages."""
    part1 = "Here is a data file to analyze:"
    part2 = "col_a,col_b\n1,2\n3,4"
    bridge = AgentBridge(
        AgentState(
            messages=[ChatMessageUser(content=part1), ChatMessageUser(content=part2)]
        )
    )

    # title call re-sends only the first input message (plus its preamble)
    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a title generator ..."),
            ChatMessageUser(content="Generate a title for this conversation:\n"),
            ChatMessageUser(content=part1),
        ],
        "CSV analysis session",
    )

    # the real task call carries both input messages
    await track(
        bridge,
        [
            TASK_SYSTEM,
            ChatMessageUser(content=part1),
            ChatMessageUser(content=part2),
        ],
        "The columns sum to 4 and 6.",
    )

    assert bridge.state.output.completion == "The columns sum to 4 and 6."
    assert len(bridge.state.messages) == 4


async def test_system_only_initial_input_uses_legacy_fallback() -> None:
    # an initial input with no non-system messages provides no descent anchor;
    # accumulation and side-call rejection must still work via the legacy path
    bridge = AgentBridge(
        AgentState(messages=[ChatMessageSystem(content="You are a helpful agent.")])
    )

    turn1: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    out1 = await track(bridge, turn1, "working")
    turn2 = turn1 + [out1.message, ChatMessageTool(content="tool result")]
    await track(bridge, turn2, "Castle")
    assert bridge.state.output.completion == "Castle"

    await track(bridge, [ChatMessageUser(content="side call")], "side answer")
    assert bridge.state.output.completion == "Castle"


# ---------------------------------------------------------------------------
# Side-call interleaving
# ---------------------------------------------------------------------------


async def test_longer_side_call_between_main_loop_turns_is_ignored() -> None:
    """A longer side call landing mid-loop must not derail the main thread.

    Under the previous length heuristic the side call both displaced the
    state *and* raised the bar above the main loop's next turn, so tracking
    never recovered. The main loop's next turn extends the tracked thread and
    must win regardless of the intervening call's length.
    """
    bridge = task_bridge()

    turn1: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    out1 = await track(bridge, turn1, "working")

    # longer side call lands between main-loop turns
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
    assert bridge.state.output.completion == "working"

    # main loop resumes (same length as the side call's total, still wins)
    turn2 = turn1 + [out1.message, ChatMessageTool(content="tool result")]
    await track(bridge, turn2, "Castle")

    assert bridge.state.output.completion == "Castle"
    assert len(bridge.state.messages) == len(turn2) + 1


async def test_repeated_title_calls_then_task_call_wins() -> None:
    # a retried title-generation call must not establish itself as a
    # multi-call thread that the task call can no longer displace
    bridge = task_bridge()

    await track(bridge, title_generation_input(), "Doctor Who Series 9 setting")
    await track(bridge, title_generation_input(), "Doctor Who Series 9")

    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=TASK)], "Castle")

    assert bridge.state.output.completion == "Castle"
    assert len(bridge.state.messages) == 3


async def test_multiple_distinct_side_calls_then_task_call_wins() -> None:
    bridge = task_bridge()

    await track(bridge, title_generation_input(), "Doctor Who Series 9 setting")
    await track(
        bridge,
        [ChatMessageUser(content="Detect the paths in this bash command: ls /tmp")],
        "/tmp",
    )

    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=TASK)], "Castle")

    assert bridge.state.output.completion == "Castle"
    assert len(bridge.state.messages) == 3


async def test_title_call_then_multi_turn_main_loop() -> None:
    """After displacing the title call, the main loop keeps extending."""
    bridge = task_bridge()

    await track(bridge, title_generation_input(), "Doctor Who Series 9 setting")

    turn1: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    out1 = await track(bridge, turn1, "working")
    assert bridge.state.output.completion == "working"

    turn2 = turn1 + [out1.message, ChatMessageTool(content="tool result")]
    out2 = await track(bridge, turn2, "more work")
    assert bridge.state.output.completion == "more work"

    turn3 = turn2 + [out2.message, ChatMessageTool(content="tool result 2")]
    await track(bridge, turn3, "Castle")

    assert bridge.state.output.completion == "Castle"
    assert len(bridge.state.messages) == len(turn3) + 1


# ---------------------------------------------------------------------------
# Task prompts condensed to attachment references
# ---------------------------------------------------------------------------


def condensed(text: str) -> str:
    """The attachment reference a text condenses to (see log/_condense.py)."""
    return f"attachment://{mm3_hash(text)}"


async def test_condensed_user_turn_anchors_descent() -> None:
    """A main loop whose user turn arrives condensed must still win.

    A long task prompt that rides into the scaffold via inspect's transcript
    condensation crosses the bridge as an `attachment://<hash>` placeholder
    rather than the original text (observed with opencode on single-turn
    GAIA). Descent must still anchor on the initial input: under the length
    fallback the earlier 3-message title call outranks the 2-message answer
    call and `state.output` ends up as the session title.
    """
    bridge = task_bridge()

    # title call fires first; the scaffold's store holds the condensed turn
    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a title generator ..."),
            ChatMessageUser(content="Generate a title for this conversation:\n"),
            ChatMessageUser(content=condensed(TASK)),
        ],
        "Doctor Who Series 9 setting",
    )

    # single-turn answer call: the user turn is the condensed placeholder
    await track(
        bridge, [TASK_SYSTEM, ChatMessageUser(content=condensed(TASK))], "Castle"
    )

    assert bridge.state.output.completion == "Castle"
    assert [m.text for m in bridge.state.messages] == [
        TASK_SYSTEM.text,
        condensed(TASK),
        "Castle",
    ]


async def test_condensed_main_loop_keeps_extending() -> None:
    """After a condensed turn anchors descent the loop tracks normally."""
    bridge = task_bridge()

    await track(bridge, title_generation_input(), "Doctor Who Series 9 setting")

    turn1: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=condensed(TASK))]
    out1 = await track(bridge, turn1, "working")
    assert bridge.state.output.completion == "working"

    turn2 = turn1 + [out1.message, ChatMessageTool(content="tool result")]
    await track(bridge, turn2, "Castle")

    assert bridge.state.output.completion == "Castle"
    assert len(bridge.state.messages) == len(turn2) + 1


async def test_partially_condensed_multi_message_input_anchors_descent() -> None:
    """Only long input messages condense; descent matches per message."""
    part1 = "Analyze the attached data file."
    part2 = "col_a,col_b\n" + "\n".join(f"{i},{i * 2}" for i in range(100))
    bridge = AgentBridge(
        AgentState(
            messages=[ChatMessageUser(content=part1), ChatMessageUser(content=part2)]
        )
    )

    await track(bridge, title_generation_input(), "CSV analysis session")

    # short message crosses verbatim, long one as an attachment reference
    await track(
        bridge,
        [
            TASK_SYSTEM,
            ChatMessageUser(content=part1),
            ChatMessageUser(content=condensed(part2)),
        ],
        "The columns sum as expected.",
    )

    assert bridge.state.output.completion == "The columns sum as expected."
    assert len(bridge.state.messages) == 4


async def test_unrelated_attachment_reference_does_not_anchor_descent() -> None:
    """Only the initial input's own condensed form matches.

    A side call whose first user turn is an attachment reference to *other*
    content must not descend: if it did (e.g. if any placeholder were treated
    as a wildcard) it would take over as the descending thread and the real
    answer call could no longer displace it.
    """
    bridge = task_bridge()

    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a title generator ..."),
            ChatMessageUser(content="Generate a title for this conversation:\n"),
            ChatMessageUser(content=condensed(TASK)),
        ],
        "Doctor Who Series 9 setting",
    )

    # side call summarizing an attachment reference to different content
    await track(
        bridge,
        [ChatMessageUser(content=condensed("some tool output blob"))],
        "summary of the blob",
    )

    # the real answer call must still displace the (non-descending) title call
    await track(
        bridge, [TASK_SYSTEM, ChatMessageUser(content=condensed(TASK))], "Castle"
    )

    assert bridge.state.output.completion == "Castle"
    assert bridge.state.messages[-1].text == "Castle"


# ---------------------------------------------------------------------------
# Scaffolds that rewrite the input prompt (no fingerprint/descent continuity)
# ---------------------------------------------------------------------------


def rewritten_task(call: int | None = None) -> ChatMessageUser:
    """The task message as rewritten by the scaffold.

    Mirrors e.g. claude code's system-reminder injection; `call` varies the
    text per call.
    """
    reminder = f"<system-reminder>call {call}</system-reminder>" if call else ""
    return ChatMessageUser(content=f"{TASK}\n{reminder}")


async def test_rewriting_scaffold_tracks_via_legacy_heuristic() -> None:
    """A scaffold that rewrites the prompt *every call* still tracks its loop.

    Per-call rewriting breaks both fingerprint continuity (no extension) and
    descent (never anchored), so tracking runs entirely on the legacy
    previous-call length comparison — which must keep working.
    """
    bridge = task_bridge()

    call1: list[ChatMessage] = [TASK_SYSTEM, rewritten_task(1)]
    out1 = await track(bridge, call1, "working")
    assert bridge.state.output.completion == "working"

    call2: list[ChatMessage] = [
        TASK_SYSTEM,
        rewritten_task(2),
        ChatMessageAssistant(content=out1.message.text),
        ChatMessageTool(content="tool result"),
    ]
    out2 = await track(bridge, call2, "more work")
    assert bridge.state.output.completion == "more work"

    # shorter side call ignored
    await track(bridge, [ChatMessageUser(content="side call")], "side answer")
    assert bridge.state.output.completion == "more work"

    call3: list[ChatMessage] = [
        TASK_SYSTEM,
        rewritten_task(3),
        ChatMessageAssistant(content=out1.message.text),
        ChatMessageTool(content="tool result"),
        ChatMessageAssistant(content=out2.message.text),
        ChatMessageTool(content="tool result 2"),
    ]
    await track(bridge, call3, "Castle")

    assert bridge.state.output.completion == "Castle"
    assert len(bridge.state.messages) == len(call3) + 1


async def test_rewriting_scaffold_recovers_from_compaction() -> None:
    """A stably-rewritten (non-descending) loop still recovers from compaction."""
    bridge = task_bridge()

    # loop with a stable rewritten prompt: extension works, descent never does
    turn1: list[ChatMessage] = [TASK_SYSTEM, rewritten_task()]
    out1 = await track(bridge, turn1, "working")
    turn2 = turn1 + [out1.message, ChatMessageTool(content="tool result")]
    out2 = await track(bridge, turn2, "more work")
    turn3 = turn2 + [out2.message, ChatMessageTool(content="tool result 2")]
    await track(bridge, turn3, "even more work")

    # compaction replaces the history with a summary; the new loop neither
    # extends the tracked thread nor descends, so it recovers via candidate
    # promotion when its next call extends it
    compact1: list[ChatMessage] = [
        TASK_SYSTEM,
        ChatMessageUser(content="Summary of the conversation so far: ..."),
    ]
    cout1 = await track(bridge, compact1, "compacted work")
    compact2 = compact1 + [cout1.message, ChatMessageTool(content="tool result 3")]
    await track(bridge, compact2, "Castle")

    assert bridge.state.output.completion == "Castle"
    assert len(bridge.state.messages) == len(compact2) + 1


# ---------------------------------------------------------------------------
# Checkpoint resume
# ---------------------------------------------------------------------------


async def test_resume_anchors_descent_on_original_input() -> None:
    """On checkpoint resume, descent anchors on the *original* input.

    A resumed agent state carries the full restored conversation, but the
    checkpointer restores the compaction prefix to the original input, and the
    descent anchor must come from that prefix. If it were (wrongly) derived
    from the resumed state's messages, neither the replayed task call nor the
    title call would descend and the longer title call would win.
    """
    original_input: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    restored_conversation: list[ChatMessage] = [
        TASK_SYSTEM,
        ChatMessageUser(content=TASK),
        ChatMessageAssistant(content="working"),
        ChatMessageTool(content="tool result"),
        ChatMessageAssistant(content="prior answer"),
    ]
    cp = RecordingCheckpointer(
        restored={"bridge_compaction_prefix": original_input.copy()}
    )
    bridge = AgentBridge(
        AgentState(messages=restored_conversation.copy()), checkpointer=cp
    )

    # the scaffold restarts: title call fires first again
    await track(bridge, title_generation_input(), "Doctor Who Series 9 setting")

    # replayed one-shot task call must win
    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=TASK)], "Castle")

    assert bridge.state.output.completion == "Castle"
    assert len(bridge.state.messages) == 3


# ---------------------------------------------------------------------------
# End-to-end through the real request handlers
# ---------------------------------------------------------------------------

BRIDGE_MODEL = "claude-opus-4"


def scenario_model(completions: list[str]) -> Model:
    def output(completion: str) -> ModelOutput:
        out = ModelOutput.from_content("mockllm/model", completion)
        # pre-set usage so mockllm skips its count_tokens estimate (which
        # downloads a tiktoken encoding, requiring network access)
        out.usage = ModelUsage(
            input_tokens=1, output_tokens=len(completion), total_tokens=1
        )
        return out

    return get_model(
        "mockllm/model",
        memoize=False,
        custom_outputs=[output(completion) for completion in completions],
    )


async def test_completions_handler_tracks_main_thread_end_to_end() -> None:
    """The opencode scenario through the real OpenAI completions handler.

    Exercises message conversion, system-prompt handling and message-id
    assignment together with `_track_state`: `apply_message_ids` gives every
    request fresh ids, so thread continuity must survive the full request
    path, not just hand-constructed messages.
    """
    model = scenario_model(
        ["Doctor Who Series 9 setting", "let me look into that", "Castle"]
    )
    bridge = AgentBridge(
        AgentState(messages=[ChatMessageUser(content=TASK)]),
        model_aliases={BRIDGE_MODEL: model},
    )

    async def request(messages: list[dict[str, str]]) -> str:
        completion = await inspect_completions_api_request(
            {"model": BRIDGE_MODEL, "messages": messages}, None, bridge
        )
        return completion.choices[0].message.content or ""

    # opencode's title-generation call lands first
    await request(
        [
            {"role": "system", "content": "You are a title generator ..."},
            {"role": "user", "content": "Generate a title for this conversation:\n"},
            {"role": "user", "content": TASK},
        ]
    )

    # main loop: turn 1
    main = [
        {"role": "system", "content": "You are opencode, an agent that ..."},
        {"role": "user", "content": TASK},
    ]
    reply = await request(main)
    assert reply == "let me look into that"
    assert bridge.state.output.completion == "let me look into that"

    # main loop: turn 2 (scaffold round-trips through its own store)
    main = main + [
        {"role": "assistant", "content": reply},
        {"role": "user", "content": "please continue"},
    ]
    await request(main)

    assert bridge.state.output.completion == "Castle"
    assert [m.text for m in bridge.state.messages] == [
        "You are opencode, an agent that ...",
        TASK,
        "let me look into that",
        "please continue",
        "Castle",
    ]


async def test_anthropic_handler_tracks_main_thread_end_to_end() -> None:
    """The opencode scenario through the real Anthropic messages handler."""
    model = scenario_model(
        ["Doctor Who Series 9 setting", "let me look into that", "Castle"]
    )
    bridge = AgentBridge(
        AgentState(messages=[ChatMessageUser(content=TASK)]),
        model_aliases={BRIDGE_MODEL: model},
    )

    async def request(system: str, messages: list[dict[str, Any]]) -> str:
        message = await inspect_anthropic_api_request(
            {
                "model": BRIDGE_MODEL,
                "max_tokens": 1024,
                "system": system,
                "messages": messages,
            },
            None,
            internal_web_search_providers(),
            default_code_execution_providers(),
            bridge,
        )
        block = message.content[0]
        assert block.type == "text"
        return block.text

    # opencode's title-generation call lands first
    await request(
        "You are a title generator ...",
        [
            {"role": "user", "content": "Generate a title for this conversation:\n"},
            {"role": "user", "content": TASK},
        ],
    )

    # main loop: turn 1
    main: list[dict[str, Any]] = [{"role": "user", "content": TASK}]
    reply = await request("You are opencode, an agent that ...", main)
    assert reply == "let me look into that"
    assert bridge.state.output.completion == "let me look into that"

    # main loop: turn 2
    main = main + [
        {"role": "assistant", "content": reply},
        {"role": "user", "content": "please continue"},
    ]
    await request("You are opencode, an agent that ...", main)

    assert bridge.state.output.completion == "Castle"
    assert [m.text for m in bridge.state.messages] == [
        "You are opencode, an agent that ...",
        TASK,
        "let me look into that",
        "please continue",
        "Castle",
    ]


# ---------------------------------------------------------------------------
# accumulate_conversations: keep every conversation, not just the main one
# ---------------------------------------------------------------------------


def accumulating_bridge() -> AgentBridge:
    return AgentBridge(
        AgentState(messages=[ChatMessageUser(content=TASK)]),
        accumulate_conversations=True,
    )


def cc_system(nonce: int) -> ChatMessageSystem:
    """Claude Code's system prompt, which carries a per-request cache token."""
    return ChatMessageSystem(
        content=f"x-anthropic-billing-header: cc_version=2.1.126; cch={nonce:05x};\n\nYou are a Claude agent."
    )


async def test_every_conversation_is_kept_not_just_the_main_one() -> None:
    """Two independent conversations (e.g. two `claude -p` runs) both reach the state."""
    bridge = accumulating_bridge()

    first: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    out = await track(bridge, first, "castle answer")
    await track(
        bridge, first + [out.message, ChatMessageTool(content="t")], "castle detail"
    )

    second: list[ChatMessage] = [
        TASK_SYSTEM,
        ChatMessageUser(content="Unrelated second question."),
    ]
    await track(bridge, second, "second answer")

    texts = [m.text for m in bridge.state.messages]
    assert "castle detail" in texts
    assert "second answer" in texts
    assert texts.index("castle detail") < texts.index("second answer")
    # the first conversation is kept once, in its longest form -- not once per call
    assert texts.count("castle answer") == 1
    # output describes the final message
    assert bridge.state.output.completion == "second answer"
    assert texts[-1] == "second answer"


async def test_accumulation_survives_a_per_request_system_prompt() -> None:
    """A growing Claude Code conversation is ONE conversation, not one per call."""
    bridge = accumulating_bridge()

    turn: list[ChatMessage] = [cc_system(1), ChatMessageUser(content=TASK)]
    out = await track(bridge, turn, "step 1")
    for step in range(2, 5):
        turn = [cc_system(step), *turn[1:], out.message, ChatMessageTool(content="t")]
        out = await track(bridge, turn, f"step {step}")

    texts = [m.text for m in bridge.state.messages]
    assert texts.count("step 1") == 1
    assert texts.count(TASK) == 1
    assert texts[-1] == "step 4"


async def test_accumulation_keeps_divergent_answers_to_one_history() -> None:
    """Two answers to an identical history stay separate rather than being merged."""
    bridge = accumulating_bridge()

    history: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    await track(bridge, history, "answer A")
    await track(bridge, history, "answer B")

    texts = [m.text for m in bridge.state.messages]
    assert "answer A" in texts
    assert "answer B" in texts


async def test_main_thread_tracking_is_the_default() -> None:
    """Without the flag the bridge still surfaces one main conversation."""
    bridge = task_bridge()

    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=TASK)], "castle answer")
    await track(
        bridge, [TASK_SYSTEM, ChatMessageUser(content="Unrelated.")], "second answer"
    )

    assert "second answer" not in [m.text for m in bridge.state.messages]


async def test_a_repeated_call_does_not_fork_a_replica() -> None:
    """An exact repeat is the same conversation, not a new one.

    Two invocations making the same deterministic aux call (claude code's bash-path probe)
    fingerprint identically. Requiring a strict extension forks a whole replica on each.
    """
    bridge = accumulating_bridge()

    call: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    await track(bridge, call, "Castle")
    await track(bridge, call, "Castle")

    assert [m.text for m in bridge.state.messages] == [TASK_SYSTEM.text, TASK, "Castle"]


async def test_a_resend_after_growth_is_absorbed_not_stranded() -> None:
    """A re-sent earlier turn carries nothing the grown conversation does not.

    Appending it instead strands a fork that can never re-merge -- every later call
    extends the longer copy -- leaving a stale duplicate at the end of state.messages.
    """
    bridge = accumulating_bridge()

    first: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    out = await track(bridge, first, "working")
    grown = [*first, out.message, ChatMessageTool(content="tool result")]
    await track(bridge, grown, "Castle")
    await track(bridge, first, "working")

    texts = [m.text for m in bridge.state.messages]
    assert texts == [TASK_SYSTEM.text, TASK, "working", "tool result", "Castle"]


async def test_a_late_side_call_does_not_poison_the_output() -> None:
    """state.output is the newest call, not whichever conversation started last.

    Indexing it by conversation order lets one aux call landing after the main loop's
    first turn own the output for the rest of the run -- the meridianlabs-ai/inspect_ai#140
    failure this tracker exists to prevent.
    """
    bridge = accumulating_bridge()

    first: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    out = await track(bridge, first, "working")
    await track(bridge, [ChatMessageUser(content="Detect paths in: ls /tmp")], "/tmp")
    await track(bridge, [*first, out.message, ChatMessageTool(content="t")], "Castle")

    assert bridge.state.output.completion == "Castle"


async def test_accumulated_message_ids_are_unique_and_stable() -> None:
    """Accumulated message ids must be unique AND stable.

    Ids are content-derived and each request sees only its own conversation, so
    independent conversations that repeat a turn arrive carrying the SAME id while
    `ChatMessage.id` is documented unique.

    The re-assigned id must be allocated ONCE and held: re-deriving it per call hands the
    same message a new id every generation, defeating the stability `apply_message_ids`
    provides and breaking every consumer that joins on the id.
    """
    bridge = accumulating_bridge()

    await track(bridge, [ChatMessageUser(content="question one", id="collide")], "A")
    await track(bridge, [ChatMessageUser(content="question two", id="collide")], "B")
    first = [m.id for m in bridge.state.messages]

    for index in range(3):
        await track(bridge, [ChatMessageUser(content=f"other {index}")], f"o{index}")
    later = [m.id for m in bridge.state.messages]

    assert len(later) == len(set(later))
    assert later[: len(first)] == first


async def test_accumulated_conversations_keep_first_seen_order() -> None:
    """A call resuming an earlier conversation does not move it to the end."""
    bridge = accumulating_bridge()

    first: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    out = await track(bridge, first, "first answer")

    second: list[ChatMessage] = [
        TASK_SYSTEM,
        ChatMessageUser(content="Second question."),
    ]
    await track(bridge, second, "second answer")

    resumed = [*first, out.message, ChatMessageTool(content="t")]
    await track(bridge, resumed, "first conversation continues")

    texts = [m.text for m in bridge.state.messages]
    assert texts.index("first conversation continues") < texts.index("second answer")
    # state.output is the newest work, which is the resumed conversation -- so with
    # accumulation the last message and state.output need not be the same turn.
    assert bridge.state.output.completion == "first conversation continues"
    assert texts[-1] == "second answer"


async def test_accumulated_conversations_survive_a_resume() -> None:
    """A resumed run keeps the conversations it already saw, and a replay does not duplicate.

    The scaffold replays only the conversation it was in, so dropping the rest on resume
    would lose every earlier one -- and those are the whole point of accumulating. What
    made dropping them look necessary was appending a replayed call as a new conversation;
    an equal-or-contained call is now absorbed instead.
    """
    first = accumulating_bridge()
    session_one: list[ChatMessage] = [TASK_SYSTEM, ChatMessageUser(content=TASK)]
    await track(first, session_one, "session one answer")
    session_two: list[ChatMessage] = [
        TASK_SYSTEM,
        ChatMessageUser(content="Second question."),
    ]
    out_two = await track(first, session_two, "session two answer")

    # resume with that state, then let the scaffold replay session two and continue it
    checkpointer = RecordingCheckpointer(
        restored={"bridge_conversations": first._conversations}
    )
    resumed = AgentBridge(
        AgentState(messages=[ChatMessageUser(content=TASK)]),
        accumulate_conversations=True,
        checkpointer=checkpointer,
    )
    await track(resumed, session_two, "session two answer")
    await track(
        resumed,
        [*session_two, out_two.message, ChatMessageTool(content="t")],
        "session two continues",
    )

    texts = [m.text for m in resumed.state.messages]
    assert "session one answer" in texts
    assert texts.count("session two answer") == 1
    assert texts[-1] == "session two continues"
