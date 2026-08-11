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
# Scaffold-decorated task prompts (containment anchoring)
# ---------------------------------------------------------------------------


async def test_quote_wrapped_prompt_anchors_descent() -> None:
    """Opencode round-trips the prompt wrapped in literal double quotes.

    Single-turn GAIA reproduction: the real task call fires first (answering
    in one turn), then the longer title-generation call lands. Neither call
    carries the initial text verbatim or condensed, so without containment
    anchoring both threads are non-descending and the legacy length fallback
    adopts the title thread as the final state (`state.output` becomes the
    session title and the sample scores 0).
    """
    bridge = task_bridge()
    quoted = f'"{TASK}"'

    # the real task call (single-turn agent loop, quoted prompt)
    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=quoted)], "Castle")

    # title call fires after (opencode quotes the prompt here too)
    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a title generator ..."),
            ChatMessageUser(content="Generate a title for this conversation:\n"),
            ChatMessageUser(content=quoted),
        ],
        "Doctor Who Series 9 setting",
    )

    assert bridge.state.output.completion == "Castle"
    assert [m.text for m in bridge.state.messages] == [
        TASK_SYSTEM.text,
        quoted,
        "Castle",
    ]


async def test_quote_wrapped_prompt_title_call_first() -> None:
    """Same quote-wrapping with the title call landing before the task call."""
    bridge = task_bridge()
    quoted = f'"{TASK}"'

    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a title generator ..."),
            ChatMessageUser(content="Generate a title for this conversation:\n"),
            ChatMessageUser(content=quoted),
        ],
        "Doctor Who Series 9 setting",
    )

    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=quoted)], "Castle")

    assert bridge.state.output.completion == "Castle"
    assert bridge.state.messages[-1].text == "Castle"


async def test_short_quote_wrapped_prompt_anchors_descent() -> None:
    """Exact quote-wrapping anchors even below the containment length floor.

    With a short task, generic containment is floor-gated, so without a
    dedicated quote-wrap arm both threads grade NO and the legacy length arm
    adopts the longer title call (the reported opencode failure, just with a
    short prompt).
    """
    short_task = "Solve 2+2"
    bridge = AgentBridge(AgentState(messages=[ChatMessageUser(content=short_task)]))
    quoted = f'"{short_task}"'

    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=quoted)], "4")

    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a title generator ..."),
            ChatMessageUser(content="Generate a title for this conversation:\n"),
            ChatMessageUser(content=quoted),
        ],
        "Simple arithmetic",
    )

    assert bridge.state.output.completion == "4"


async def test_short_quote_wrapped_prompt_with_whitespace_anchors_descent() -> None:
    """Whitespace inside the quotes must not defeat the quote-wrap anchor.

    opencode quotes the *original* prompt, so whitespace around the task
    survives inside the wrapper while the anchor text is stored stripped;
    the comparison must normalize the quote interior, not just the outside.
    """
    short_task = "  Solve 2+2  "
    bridge = AgentBridge(AgentState(messages=[ChatMessageUser(content=short_task)]))
    quoted = f'"{short_task}"'

    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=quoted)], "4")

    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a title generator ..."),
            ChatMessageUser(content="Generate a title for this conversation:\n"),
            ChatMessageUser(content=quoted),
        ],
        "Simple arithmetic",
    )

    assert bridge.state.output.completion == "4"


async def test_verbatim_side_call_does_not_displace_quote_wrapped_main() -> None:
    """A side call resending the raw task must not beat the quoted main call.

    With a quote-wrapping scaffold the real call carries the *decorated*
    prompt while a side call (e.g. a topic detector) copies the *raw* input
    verbatim. The verbatim resend must not be mistaken for the main thread:
    quote-wrap is the scaffold's store transform, so it is stronger evidence
    of the persisted main conversation than a raw copy.
    """
    bridge = task_bridge()
    quoted = f'"{TASK}"'

    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=quoted)], "Castle")

    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a topic detector ..."),
            ChatMessageUser(content=TASK),
        ],
        "Doctor Who",
    )

    assert bridge.state.output.completion == "Castle"


async def test_quote_wrapped_main_displaces_verbatim_side_call() -> None:
    """Reverse order: the quoted main call reclaims tracking from the side call."""
    bridge = task_bridge()
    quoted = f'"{TASK}"'

    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a topic detector ..."),
            ChatMessageUser(content=TASK),
        ],
        "Doctor Who",
    )

    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=quoted)], "Castle")

    assert bridge.state.output.completion == "Castle"
    assert bridge.state.messages[-1].text == "Castle"


async def test_bare_quoted_side_call_displaces_exact_main() -> None:
    """Pins the accepted losing side of the `QUOTED` > `EXACT` ordering.

    Under a scaffold that does *not* quote-wrap its store, a side call whose
    whole aligned message is exactly the quoted prompt presents the same
    observables as the two tests above — one QUOTED one-shot vs one EXACT
    one-shot — so any static ordering fails exactly one of the two shapes
    (see `_Descent`). The ordering favors the observed opencode shape, so
    this constructed side call wins here. If this test starts failing the
    trade has been re-decided: re-verify
    `test_verbatim_side_call_does_not_displace_quote_wrapped_main`,
    `test_quote_wrapped_main_displaces_verbatim_side_call`, and the
    partially-quoted pair below, which break under a QUOTED == EXACT tie.
    """
    bridge = task_bridge()
    quoted = f'"{TASK}"'

    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=TASK)], "Castle")

    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a topic detector ..."),
            ChatMessageUser(content=quoted),
        ],
        "Doctor Who",
    )

    # pinned trade-off, not desired behavior: the bare-quoted side call
    # outranks the verbatim one-shot main
    assert bridge.state.output.completion == "Doctor Who"


async def test_bare_quoted_side_call_arriving_first_retains_tracking() -> None:
    """Reverse order of the pinned trade: the exact main cannot reclaim.

    The bare-quoted side call is adopted first (best information so far);
    the verbatim main's weaker `EXACT` anchor cannot displace it and, as a
    one-shot, is parked as a candidate nothing extends. A multi-turn main
    still reclaims tracking via candidate promotion — exposure is limited
    to one-shot mains.
    """
    bridge = task_bridge()
    quoted = f'"{TASK}"'

    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a topic detector ..."),
            ChatMessageUser(content=quoted),
        ],
        "Doctor Who",
    )

    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=TASK)], "Castle")

    # pinned trade-off, not desired behavior (see
    # test_bare_quoted_side_call_displaces_exact_main)
    assert bridge.state.output.completion == "Doctor Who"


async def test_contained_side_call_does_not_displace_quote_wrapped_main() -> None:
    """A longer prompt-embedding side call must not beat the quoted main call.

    The inline-prompt side-call tests below use a verbatim main thread; with
    opencode the main thread is quote-wrapped, so the side call that embeds
    the task in its first user message must lose to it as well — including
    on the equal-verdict length arm, which must never see this pair as a tie
    (quote-wrap grades above generic containment).
    """
    bridge = task_bridge()
    quoted = f'"{TASK}"'

    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=quoted)], "Castle")

    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a topic detector ..."),
            ChatMessageUser(content=f"Classify:\n{TASK}"),
            ChatMessageUser(content="Return only the topic"),
        ],
        "Doctor Who",
    )

    assert bridge.state.output.completion == "Castle"


async def test_quote_wrapped_main_displaces_contained_side_call() -> None:
    """Reverse order: the quoted main call reclaims tracking from the side call."""
    bridge = task_bridge()
    quoted = f'"{TASK}"'

    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a topic detector ..."),
            ChatMessageUser(content=f"Classify:\n{TASK}"),
            ChatMessageUser(content="Return only the topic"),
        ],
        "Doctor Who",
    )

    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=quoted)], "Castle")

    assert bridge.state.output.completion == "Castle"
    assert bridge.state.messages[-1].text == "Castle"


async def test_decorated_prompt_anchors_descent() -> None:
    """Containment also covers scaffolds that prefix/suffix the prompt."""
    bridge = task_bridge()
    decorated = f"## Task\n\n{TASK}\n\nRespond concisely."

    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=decorated)], "Castle")

    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a title generator ..."),
            ChatMessageUser(content="Generate a title for this conversation:\n"),
            ChatMessageUser(content=decorated),
        ],
        "Doctor Who Series 9 setting",
    )

    assert bridge.state.output.completion == "Castle"


async def test_quote_wrapped_condensed_placeholder_anchors_descent() -> None:
    """Decoration composes with condensation: a quoted placeholder anchors.

    Both transformations were observed separately on the same opencode code
    path (the prompt crossing as an `attachment://` placeholder, and the
    prompt quote-wrapped), so a quote-wrapped placeholder must anchor too.
    """
    bridge = task_bridge()
    quoted_placeholder = f'"{condensed(TASK)}"'

    await track(
        bridge, [TASK_SYSTEM, ChatMessageUser(content=quoted_placeholder)], "Castle"
    )

    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a title generator ..."),
            ChatMessageUser(content="Generate a title for this conversation:\n"),
            ChatMessageUser(content=quoted_placeholder),
        ],
        "Doctor Who Series 9 setting",
    )

    assert bridge.state.output.completion == "Castle"


async def test_inline_prompt_quoting_side_call_does_not_displace_exact_thread() -> None:
    """A side call quoting the prompt inside its first message must not win.

    A hypothetical scaffold could interpolate the whole prompt into the title
    call's first non-system message; that call then anchors by containment.
    Containment is weaker evidence than the main loop's exact anchor, so the
    longer title call must not displace the tracked one-shot answer.
    """
    bridge = task_bridge()

    # real task call carries the prompt verbatim (exact anchor)
    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=TASK)], "Castle")

    # longer title call with the prompt inlined into its preamble message
    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a title generator ..."),
            ChatMessageUser(content=f"Generate a title for this conversation:\n{TASK}"),
            ChatMessageUser(content="Respond with the title only."),
        ],
        "Doctor Who Series 9 setting",
    )

    assert bridge.state.output.completion == "Castle"


async def test_exact_thread_displaces_inline_prompt_quoting_side_call() -> None:
    """The exact-anchored task call reclaims tracking from an inlined title call.

    When the prompt-inlining title call lands first it is adopted (best
    information so far) with a containment anchor; the real task call's
    stronger exact anchor must displace it even though the task call is
    shorter.
    """
    bridge = task_bridge()

    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a title generator ..."),
            ChatMessageUser(content=f"Generate a title for this conversation:\n{TASK}"),
            ChatMessageUser(content="Respond with the title only."),
        ],
        "Doctor Who Series 9 setting",
    )

    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=TASK)], "Castle")

    assert bridge.state.output.completion == "Castle"
    assert bridge.state.messages[-1].text == "Castle"


async def test_assistant_message_containing_prompt_does_not_anchor() -> None:
    """Containment requires role parity with the initial message.

    A side call whose first non-system message is an *assistant* message
    quoting the prompt (e.g. a compaction/summary replay) must not anchor:
    against a containment-anchored (quote-wrapped) main thread it would
    otherwise tie the descent verdict and win on length.
    """
    bridge = task_bridge()
    quoted = f'"{TASK}"'

    # quote-wrapped one-shot main loop (containment anchor)
    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=quoted)], "Castle")

    # longer side call led by an assistant message that contains the prompt
    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a summarizer ..."),
            ChatMessageAssistant(content=f"Earlier the user asked: {TASK}"),
            ChatMessageUser(content="Summarize the conversation so far."),
        ],
        "The user asked about Doctor Who.",
    )

    assert bridge.state.output.completion == "Castle"


async def test_multi_message_input_with_partial_decoration_anchors_descent() -> None:
    """Per-position matching: one decorated message, one verbatim."""
    part1 = "Here is a data file to analyze in detail:"
    part2 = "col_a,col_b\n1,2\n3,4"
    bridge = AgentBridge(
        AgentState(
            messages=[ChatMessageUser(content=part1), ChatMessageUser(content=part2)]
        )
    )

    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a title generator ..."),
            ChatMessageUser(content="Generate a title for this conversation:\n"),
            ChatMessageUser(content=f'"{part1}"'),
        ],
        "CSV analysis session",
    )

    # first input message quote-wrapped, second verbatim
    await track(
        bridge,
        [
            TASK_SYSTEM,
            ChatMessageUser(content=f'"{part1}"'),
            ChatMessageUser(content=part2),
        ],
        "The columns sum to 4 and 6.",
    )

    assert bridge.state.output.completion == "The columns sum to 4 and 6."


def partially_quoted_bridge() -> tuple[
    AgentBridge, list[ChatMessage], list[ChatMessage]
]:
    """Multi-message input; the main call quote-wraps only the first message.

    Returns the bridge plus the main-call and side-call inputs: the main
    thread's quote-wrap evidence sits in one aligned position (the other is
    verbatim), while the side call copies both messages raw and appends an
    instruction — so it is longer and anchors verbatim at every position.
    """
    part1 = "Here is a data file to analyze in detail:"
    part2 = "col_a,col_b\n1,2\n3,4"
    bridge = AgentBridge(
        AgentState(
            messages=[ChatMessageUser(content=part1), ChatMessageUser(content=part2)]
        )
    )
    main: list[ChatMessage] = [
        TASK_SYSTEM,
        ChatMessageUser(content=f'"{part1}"'),
        ChatMessageUser(content=part2),
    ]
    side: list[ChatMessage] = [
        ChatMessageSystem(content="You are a topic detector ..."),
        ChatMessageUser(content=part1),
        ChatMessageUser(content=part2),
        ChatMessageUser(content="Return only the topic"),
    ]
    return bridge, main, side


async def test_verbatim_side_call_does_not_displace_partially_quoted_main() -> None:
    """Quote-wrap evidence survives positions that round-trip verbatim.

    If the thread verdict collapsed to its weakest position, the partially
    quoted main would grade the same as the raw-copy side call and the
    longer side call would win the equal-verdict length arm.
    """
    bridge, main, side = partially_quoted_bridge()

    await track(bridge, main, "The columns sum to 4 and 6.")
    await track(bridge, side, "CSV analysis")

    assert bridge.state.output.completion == "The columns sum to 4 and 6."


async def test_partially_quoted_main_displaces_verbatim_side_call() -> None:
    """Reverse order: the shorter quoted main reclaims tracking."""
    bridge, main, side = partially_quoted_bridge()

    await track(bridge, side, "CSV analysis")
    await track(bridge, main, "The columns sum to 4 and 6.")

    assert bridge.state.output.completion == "The columns sum to 4 and 6."


def store_copying_side_bridge() -> tuple[
    AgentBridge, list[ChatMessage], list[ChatMessage]
]:
    """Multi-message input; the side call mixes a stored copy with embedding.

    Side calls read from the scaffold's store too, so one can carry the
    quote-wrapped form of the first initial message while merely *embedding*
    the second — the quoted position must not lift the thread past the
    containment cap. The main call carries both messages verbatim.
    """
    part1 = "Here is a data file to analyze in detail:"
    part2 = "col_a,col_b\n1,2\n3,4\n5,6"
    bridge = AgentBridge(
        AgentState(
            messages=[ChatMessageUser(content=part1), ChatMessageUser(content=part2)]
        )
    )
    main: list[ChatMessage] = [
        TASK_SYSTEM,
        ChatMessageUser(content=part1),
        ChatMessageUser(content=part2),
    ]
    side: list[ChatMessage] = [
        ChatMessageSystem(content="You are a topic detector ..."),
        ChatMessageUser(content=f'"{part1}"'),
        ChatMessageUser(content=f"Classify:\n{part2}"),
        ChatMessageUser(content="Return only the topic"),
    ]
    return bridge, main, side


async def test_store_copying_side_call_does_not_displace_exact_main() -> None:
    """A quoted position must not lift an embedding side call past the cap."""
    bridge, main, side = store_copying_side_bridge()

    await track(bridge, main, "The columns sum to 9 and 12.")
    await track(bridge, side, "CSV analysis")

    assert bridge.state.output.completion == "The columns sum to 9 and 12."


async def test_exact_main_displaces_store_copying_side_call() -> None:
    """Reverse order: the exact main reclaims tracking from the side call."""
    bridge, main, side = store_copying_side_bridge()

    await track(bridge, side, "CSV analysis")
    await track(bridge, main, "The columns sum to 9 and 12.")

    assert bridge.state.output.completion == "The columns sum to 9 and 12."


async def test_short_initial_input_does_not_anchor_by_containment() -> None:
    """A trivially short prompt can't turn a side call into a descending thread.

    Containment anchoring requires a minimum of initial text: a side call
    whose preamble happens to contain a short prompt must not be adopted as
    descending (it would then displace the real one-shot answer thread).
    """
    short_task = "ls /tmp"
    bridge = AgentBridge(AgentState(messages=[ChatMessageUser(content=short_task)]))

    # real thread anchors by exact match
    await track(bridge, [TASK_SYSTEM, ChatMessageUser(content=short_task)], "Castle")

    # longer side call whose first user message contains the short prompt
    await track(
        bridge,
        [
            ChatMessageSystem(content="You are a title generator ..."),
            ChatMessageUser(content=f"Generate a title for: {short_task}"),
            ChatMessageUser(content="Respond with the title only."),
        ],
        "Listing temporary files",
    )

    assert bridge.state.output.completion == "Castle"


# ---------------------------------------------------------------------------
# Scaffolds that rewrite the input prompt (no fingerprint/descent continuity)
# ---------------------------------------------------------------------------


def rewritten_task(call: int | None = None) -> ChatMessageUser:
    """The task message as rewritten by the scaffold.

    Mirrors a scaffold that paraphrases/truncates the prompt; `call` varies
    the text per call. The rewritten text must not *contain* the original
    prompt — these tests exercise the paths where descent never anchors
    (a containing rewrite would anchor via containment; see the
    scaffold-decorated prompt tests above).
    """
    reminder = f"<system-reminder>call {call}</system-reminder>" if call else ""
    return ChatMessageUser(content=f"{TASK[:30]}... (see attached brief)\n{reminder}")


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
