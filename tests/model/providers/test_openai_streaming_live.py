"""Live stress test for the partial-output streaming feature (OpenAI).

Exercises the path:
    openai responses/chat-completions stream -> _stream_response/_stream_completion
    -> update_active_model_event_output(_partial_output_from_*(...))
    -> Transcript._event_updated -> subscriber

For each scenario we subscribe to the active transcript, capture a record
per ModelEvent notification (initial pending + each partial flush + final),
and assert the partial sequence is well-formed:

  * at least one partial with pending=True fires
  * the content-block-type tuple of each partial is a prefix of (or equal
    to) the final's content-block-type tuple (no spurious/reordered blocks)
  * tool-call count is monotone non-decreasing across the sequence
  * no partial (pending=True) record appears after the terminal
    (pending=None) record

Run with:
    env -u UV_EXCLUDE_NEWER uv --no-config run pytest \
        tests/model/providers/test_openai_streaming_live.py -v -s --runapi
"""

from __future__ import annotations

from dataclasses import dataclass

from test_helpers.utils import skip_if_no_openai

from inspect_ai.event._model import ModelEvent
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.tool import tool


@dataclass
class FlushRecord:
    uuid: str | None
    pending: bool
    content_types: tuple[str, ...]
    n_tool_calls: int


def _capture() -> tuple[Transcript, list[FlushRecord]]:
    """Init a fresh transcript and subscribe a recorder for ModelEvents."""
    transcript = Transcript()
    init_transcript(transcript)
    records: list[FlushRecord] = []

    def on_event(event: object) -> None:
        if not isinstance(event, ModelEvent):
            return
        msg = event.output.message
        content = msg.content
        # content may be a bare str for trivial outputs
        if isinstance(content, str):
            types: tuple[str, ...] = ("str",) if content else ()
        else:
            types = tuple(type(c).__name__ for c in content)
        records.append(
            FlushRecord(
                uuid=event.uuid,
                pending=bool(event.pending),
                content_types=types,
                n_tool_calls=len(msg.tool_calls or []),
            )
        )

    transcript._subscribe(on_event)
    return transcript, records


def _is_prefix(short: tuple[str, ...], long: tuple[str, ...]) -> bool:
    return long[: len(short)] == short


def _assert_well_formed(records: list[FlushRecord], scenario: str) -> None:
    assert records, f"[{scenario}] no ModelEvent notifications captured at all"

    # split into the partial/pending stream vs the terminal record
    pending = [r for r in records if r.pending]
    terminal = [r for r in records if not r.pending]

    # the very first record is the initial pending event recorded by
    # _record_model_interaction (empty output); the streamed partials follow.
    assert len(pending) >= 1, f"[{scenario}] expected >=1 pending record"

    # exactly one terminal (the completed event); it is the last record
    assert terminal, f"[{scenario}] no terminal (pending=None) record"
    assert records[-1] is terminal[-1], (
        f"[{scenario}] a pending partial fired AFTER the terminal record: "
        f"{[(r.pending, r.content_types) for r in records]}"
    )
    assert len(terminal) == 1, (
        f"[{scenario}] expected exactly one terminal record, got {len(terminal)}"
    )

    final_types = terminal[-1].content_types

    # the streamed partials (skip the initial empty pending event, which has
    # no streamed content yet) should be type-prefixes of the final, and
    # tool-call counts should be monotone.
    streamed = [r for r in pending if r.content_types or r.n_tool_calls]
    assert streamed, (
        f"[{scenario}] no streamed partial carried any content/tool_calls; "
        f"records={[(r.pending, r.content_types, r.n_tool_calls) for r in records]}"
    )

    prev_tool_calls = 0
    for r in pending:
        assert _is_prefix(r.content_types, final_types), (
            f"[{scenario}] partial content types {r.content_types} are NOT a "
            f"prefix of final {final_types}"
        )
        assert r.n_tool_calls >= prev_tool_calls, (
            f"[{scenario}] tool-call count regressed: {prev_tool_calls} -> "
            f"{r.n_tool_calls}"
        )
        prev_tool_calls = r.n_tool_calls

    # final tool-call count must dominate every partial's
    final_tcs = terminal[-1].n_tool_calls
    assert all(r.n_tool_calls <= final_tcs for r in pending), (
        f"[{scenario}] a partial reported more tool calls than the final ({final_tcs})"
    )

    # the stable ModelEvent.uuid is shared across every notification (the
    # message id changes between partials; consumers must key on uuid)
    uuids = {r.uuid for r in records}
    assert len(uuids) == 1, (
        f"[{scenario}] expected one stable ModelEvent.uuid across the sequence, "
        f"got {uuids}"
    )


def _dump(records: list[FlushRecord], scenario: str) -> None:
    print(f"\n=== {scenario} ===")
    for i, r in enumerate(records):
        print(
            f"  [{i:02d}] pending={r.pending!s:5} uuid={r.uuid} "
            f"types={r.content_types} n_tool_calls={r.n_tool_calls}"
        )


@skip_if_no_openai
async def test_streaming_partials_plain_text() -> None:
    transcript, records = _capture()
    model = get_model(
        "openai/gpt-5-mini",
        streaming=True,
        config=GenerateConfig(max_tokens=2000, reasoning_effort="minimal"),
    )
    await model.generate("Write three sentences about the history of the bicycle.")
    _dump(records, "plain_text")
    _assert_well_formed(records, "plain_text")
    # plain text final should contain a text block
    assert "ContentText" in records[-1].content_types


@skip_if_no_openai
async def test_streaming_partials_reasoning() -> None:
    transcript, records = _capture()
    model = get_model(
        "openai/gpt-5-mini",
        streaming=True,
        config=GenerateConfig(
            max_tokens=4000,
            reasoning_effort="medium",
            reasoning_summary="auto",
        ),
    )
    await model.generate(
        "Solve this logic puzzle carefully, reasoning through every step "
        "before answering: Five houses in a row are painted different "
        "colors. The green house is immediately to the left of the white "
        "house. The blue house is first. The red house owner drinks coffee. "
        "Which color is the middle (third) house, and why? Work through the "
        "constraints one at a time."
    )
    _dump(records, "reasoning")
    _assert_well_formed(records, "reasoning")
    # we expect a reasoning block to appear in the final, and ideally in a partial
    assert "ContentReasoning" in records[-1].content_types, (
        "reasoning scenario produced no ContentReasoning in final output"
    )
    streamed_reasoning = any(
        "ContentReasoning" in r.content_types for r in records if r.pending
    )
    assert streamed_reasoning, "no partial ever carried a ContentReasoning block"


@tool
def add():
    async def execute(x: int, y: int) -> int:
        """Add two integers.

        Args:
            x: first integer
            y: second integer
        """
        return x + y

    return execute


@skip_if_no_openai
async def test_streaming_partials_tool_call() -> None:
    transcript, records = _capture()
    model = get_model(
        "openai/gpt-5-mini",
        streaming=True,
        config=GenerateConfig(max_tokens=2000, reasoning_effort="minimal"),
    )
    await model.generate(
        "Use the add tool to compute 1234 plus 5678. Call the tool.",
        tools=[add()],
    )
    _dump(records, "tool_call")
    _assert_well_formed(records, "tool_call")
    assert records[-1].n_tool_calls >= 1, "tool_call scenario produced no tool calls"
