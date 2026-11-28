"""Tests for the CommunicationEvent and SwarmEvent transcript events."""

import io
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import TypeAdapter
from rich.console import Console

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.event import (
    CommunicationDelivery,
    CommunicationEvent,
    CommunicationRecord,
    CommunicationRejection,
    CommunicationSend,
    CommunicationWait,
    Event,
    SwarmEvent,
)
from inspect_ai.event._event import DiscriminatedEvent
from inspect_ai.log import read_eval_log
from inspect_ai.log._condense import ATTACHMENT_PROTOCOL
from inspect_ai.log._transcript import transcript
from inspect_ai.solver import Generate, Solver, TaskState, solver

LONG_CONTENT = "content " * 40
LONG_REASON = "reason " * 40
LONG_DATA = "data " * 40


def _sent(**kwargs: Any) -> CommunicationEvent:
    fields: dict[str, Any] = dict(
        kind="sent",
        source="inspect_swarm",
        agent="counter-6",
        agent_span_id="span-6",
        loop_span_id="loop-6",
        channel="shared_memory",
        record_ids=["w-1"],
        send=CommunicationSend(
            record=CommunicationRecord(
                id="w-1",
                kind="create",
                sender="counter-6",
                to=["counter-2"],
                recipients=["counter-2"],
                content="hello",
            )
        ),
        data={"version": 1, "record": {"op": "create"}},
    )
    fields.update(kwargs)
    return CommunicationEvent(**fields)


def _rejected(reason: str = "too many sends", **kwargs: Any) -> CommunicationEvent:
    fields: dict[str, Any] = dict(
        record_ids=["w-2"],
        send=CommunicationSend(
            record=CommunicationRecord(
                id="w-2", kind="message", sender="counter-6", content="spam"
            ),
            rejected=CommunicationRejection(control="rate", reason=reason),
        ),
    )
    fields.update(kwargs)
    return _sent(**fields)


def _delivered(**kwargs: Any) -> CommunicationEvent:
    fields: dict[str, Any] = dict(
        kind="delivered",
        source="inspect_swarm",
        agent="counter-6",
        channel="shared_memory",
        record_ids=["w-1"],
        delivery=CommunicationDelivery(recipients=["counter-2"], seq=1),
        data={"version": 1, "notify": True},
    )
    fields.update(kwargs)
    return CommunicationEvent(**fields)


def _read(**kwargs: Any) -> CommunicationEvent:
    fields: dict[str, Any] = dict(
        kind="read",
        source="inspect_swarm",
        agent="counter-2",
        nested=True,
        channel="shared_memory",
        record_ids=["w-1"],
        data={
            "version": 1,
            "listing": False,
            "files": [{"id": "f-1", "version": 1, "record": "w-1", "deleted": False}],
        },
    )
    fields.update(kwargs)
    return CommunicationEvent(**fields)


def _waited(**kwargs: Any) -> CommunicationEvent:
    fields: dict[str, Any] = dict(
        kind="waited",
        source="inspect_swarm",
        agent="counter-5",
        wait=CommunicationWait(
            id="wait-1", channels=["shared_memory"], outcome="news", duration=4.2
        ),
        data={"version": 1, "idle": 3.9},
    )
    fields.update(kwargs)
    return CommunicationEvent(**fields)


def _swarm(**kwargs: Any) -> SwarmEvent:
    fields: dict[str, Any] = dict(
        kind="member_result",
        member="counter-5",
        data={"version": 1, "status": "completed", "time": 13.2},
    )
    fields.update(kwargs)
    return SwarmEvent(**fields)


def _valid_events() -> list[Event]:
    return [
        _sent(),
        _sent(record_ids=[], send=CommunicationSend(record=_record(id=None))),
        _rejected(),
        _delivered(),
        _read(),
        _read(record_ids=[], data={}),
        _waited(),
        _swarm(),
        _swarm(kind="ledger", member=None, data={"version": 1, "members": []}),
    ]


def _record(**kwargs: Any) -> CommunicationRecord:
    fields: dict[str, Any] = dict(kind="append", sender="counter-6")
    fields.update(kwargs)
    return CommunicationRecord(**fields)


@solver
def _write_events(events: list[Event]) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        for event in events:
            transcript()._event(event)
        return state

    return solve


def _run(
    events: list[Event], tmp_path: Path, log_format: Literal["eval", "json"]
) -> str:
    task = Task(dataset=[Sample(input="x")], solver=_write_events(events))
    log = eval(
        task, model="mockllm/model", log_dir=str(tmp_path), log_format=log_format
    )[0]
    assert log.status == "success"
    return log.location


def _new_events(events: list[Event]) -> list[Event]:
    return [e for e in events if isinstance(e, CommunicationEvent | SwarmEvent)]


@pytest.mark.parametrize("log_format", ["eval", "json"])
def test_events_round_trip_through_log(
    tmp_path: Path, log_format: Literal["eval", "json"]
) -> None:
    events = _valid_events()
    location = _run(events, tmp_path, log_format)
    log = read_eval_log(location, resolve_attachments=True)
    assert log.samples
    restored = _new_events(log.samples[0].events)
    assert [e.model_dump() for e in restored] == [e.model_dump() for e in events]


@pytest.mark.parametrize("log_format", ["eval", "json"])
def test_long_strings_become_attachments(
    tmp_path: Path, log_format: Literal["eval", "json"]
) -> None:
    sent = _sent(
        send=CommunicationSend(record=_record(id="w-1", content=LONG_CONTENT)),
        data={"version": 1, "path": LONG_DATA},
    )
    rejected = [_rejected(LONG_REASON), _rejected(LONG_REASON)]
    swarm = _swarm(data={"version": 1, "reason": LONG_DATA})
    events: list[Event] = [sent, *rejected, swarm]
    location = _run(events, tmp_path, log_format)

    log = read_eval_log(location)
    assert log.samples
    condensed = _new_events(log.samples[0].events)
    c_sent, c_rejected_1, c_rejected_2, c_swarm = condensed
    assert isinstance(c_sent, CommunicationEvent) and c_sent.send is not None
    assert c_sent.send.record.content is not None
    assert c_sent.send.record.content.startswith(ATTACHMENT_PROTOCOL)
    assert str(c_sent.data["path"]).startswith(ATTACHMENT_PROTOCOL)
    reasons = []
    for event in (c_rejected_1, c_rejected_2):
        assert isinstance(event, CommunicationEvent) and event.send is not None
        assert event.send.rejected is not None
        reasons.append(event.send.rejected.reason)
    assert reasons[0].startswith(ATTACHMENT_PROTOCOL) and reasons[0] == reasons[1]
    assert isinstance(c_swarm, SwarmEvent)
    assert str(c_swarm.data["reason"]).startswith(ATTACHMENT_PROTOCOL)
    attachments = log.samples[0].attachments
    assert list(attachments.values()).count(LONG_REASON) == 1

    resolved = read_eval_log(location, resolve_attachments=True)
    assert resolved.samples
    restored = _new_events(resolved.samples[0].events)
    assert [e.model_dump() for e in restored] == [e.model_dump() for e in events]


_INVALID: list[tuple[str, dict[str, Any], str]] = [
    ("sent", dict(send=None), "send"),
    ("sent", dict(wait=_waited().wait), "wait"),
    ("sent", dict(channel=None), "channel"),
    ("sent", dict(record_ids=[]), "record_ids"),
    ("sent", dict(record_ids=["w-9"]), "record_ids"),
    ("sent", dict(record_ids=["w-1", "w-2"]), "record_ids"),
    ("delivered", dict(delivery=None), "delivery"),
    ("delivered", dict(send=_sent().send), "send"),
    ("delivered", dict(channel=None), "channel"),
    ("read", dict(send=_sent().send), "send"),
    ("read", dict(delivery=_delivered().delivery), "delivery"),
    ("read", dict(wait=_waited().wait), "wait"),
    ("read", dict(channel=None), "channel"),
    ("waited", dict(wait=None), "wait"),
    ("waited", dict(delivery=_delivered().delivery), "delivery"),
    ("waited", dict(channel="shared_memory"), "channel"),
]

_BUILDERS = {"sent": _sent, "delivered": _delivered, "read": _read, "waited": _waited}


@pytest.mark.parametrize("kind,overrides,match", _INVALID)
def test_communication_event_refuses_shape(
    kind: str, overrides: dict[str, Any], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        _BUILDERS[kind](**overrides)


def test_communication_event_refuses_shape_on_read() -> None:
    logged = _read().model_dump(mode="json")
    logged["channel"] = None
    adapter: TypeAdapter[Event] = TypeAdapter(DiscriminatedEvent)
    with pytest.raises(ValueError, match="channel"):
        adapter.validate_python(logged)


def _render(event: Event) -> tuple[str, str]:
    from inspect_ai._display.textual.widgets.transcript import render_event

    displays = render_event(event)
    assert displays is not None and len(displays) == 1
    buffer = io.StringIO()
    Console(file=buffer, width=400).print(displays[0].content)
    return displays[0].title, buffer.getvalue()


@pytest.mark.parametrize(
    "event,title,line",
    [
        (
            _sent(),
            "communication: sent",
            "counter-6 → shared_memory: create w-1 to counter-2",
        ),
        (
            _rejected(),
            "communication: sent",
            "counter-6 → shared_memory: message w-2, refused (rate)",
        ),
        (
            _delivered(),
            "communication: delivered",
            "counter-6 → shared_memory: delivered w-1 (#1) to counter-2",
        ),
        (
            _read(),
            "communication: read",
            "counter-2 (subagent) ← shared_memory: read w-1",
        ),
        (
            _waited(),
            "communication: waited",
            "counter-5 waited 4.2s on shared_memory: news",
        ),
        (
            _swarm(),
            "swarm: member_result",
            "member: counter-5",
        ),
    ],
)
def test_events_render_in_tui(event: Event, title: str, line: str) -> None:
    rendered_title, output = _render(event)
    assert rendered_title == title
    assert output.strip() == line
