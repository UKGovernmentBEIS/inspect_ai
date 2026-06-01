from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from pydantic import JsonValue
from test_helpers.transcript import make_model_event

from inspect_ai._util.constants import get_deserializing_context
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.log import expand_events
from inspect_ai.log._transcript_store import TranscriptEventStore
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.model._model_call import ModelCall

TRANSCRIPT_EVENT_STORE = "transcript_event_store.sqlite"


def _exported_events(work_dir: Path) -> list[dict[str, object]]:
    return json.loads((work_dir / "events.json").read_text())


def _write_transcript_files(store: TranscriptEventStore, work_dir: Path) -> None:
    store.write_transcript_files(
        events_path=work_dir / "events.json",
        events_data_path=work_dir / "events_data.json",
        attachments_path=work_dir / "attachments.json",
    )


def _no_attachment(_: str) -> str | None:
    return None


def test_transcript_event_store_initializes_schema(tmp_path: Path) -> None:
    store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)

    counts = store.counts()

    assert counts.events == 0
    assert counts.message_pool == 0
    assert counts.call_pool == 0
    assert counts.attachments == 0
    assert (tmp_path / TRANSCRIPT_EVENT_STORE).exists()


def test_transcript_event_store_exports_events_in_first_seen_order(
    tmp_path: Path,
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)
    first = InfoEvent(data="first")
    second = InfoEvent(data="second")

    first_id = first.uuid
    second_id = second.uuid

    transcript_store.merge_event(first, attachment_lookup=_no_attachment)
    transcript_store.merge_event(second, attachment_lookup=_no_attachment)
    _write_transcript_files(transcript_store, tmp_path)

    events = _exported_events(tmp_path)
    assert [event["data"] for event in events] == ["first", "second"]
    assert [event["uuid"] for event in events] == [first_id, second_id]


def test_transcript_event_store_updates_existing_logical_event(
    tmp_path: Path,
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)
    event = InfoEvent(data="first")

    event_id = event.uuid
    transcript_store.merge_event(event, attachment_lookup=_no_attachment)
    event.data = "updated"
    transcript_store.merge_event(event, attachment_lookup=_no_attachment)
    _write_transcript_files(transcript_store, tmp_path)

    events = _exported_events(tmp_path)
    assert len(events) == 1
    assert events[0]["uuid"] == event_id
    assert events[0]["data"] == "updated"
    assert transcript_store.counts().events == 1


def test_transcript_event_store_accepts_cross_thread_events(
    tmp_path: Path,
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)
    input_events = [InfoEvent(data=f"from-thread-{index}") for index in range(8)]

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(transcript_store.merge_event, event, _no_attachment)
            for event in input_events
        ]
        for future in futures:
            future.result()

    _write_transcript_files(transcript_store, tmp_path)

    exported_events = _exported_events(tmp_path)
    assert {event["data"] for event in exported_events} == {
        f"from-thread-{index}" for index in range(8)
    }


def test_transcript_event_store_assigns_uuid_to_uuidless_events(
    tmp_path: Path,
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)
    event = InfoEvent.model_validate(
        {"event": "info", "data": "uuidless"}, context=get_deserializing_context()
    )
    assert event.uuid is None

    transcript_store.merge_event(event, attachment_lookup=_no_attachment)
    _write_transcript_files(transcript_store, tmp_path)

    assert isinstance(event.uuid, str)
    events = _exported_events(tmp_path)
    assert len(events) == 1
    assert events[0]["uuid"] == event.uuid


def test_transcript_event_store_assigns_uuid_for_uuidless_event_updates(
    tmp_path: Path,
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)
    event = InfoEvent.model_validate(
        {"event": "info", "data": "pending", "pending": True},
        context=get_deserializing_context(),
    )
    assert event.uuid is None

    transcript_store.merge_event(event, attachment_lookup=_no_attachment)
    event.pending = False
    event.data = "done"
    transcript_store.merge_event(event, attachment_lookup=_no_attachment)
    _write_transcript_files(transcript_store, tmp_path)

    events = _exported_events(tmp_path)
    assert len(events) == 1
    assert events[0]["uuid"] == event.uuid
    assert events[0]["data"] == "done"


def test_transcript_event_store_exports_only_referenced_attachments(
    tmp_path: Path,
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)
    transcript_store.merge_event(
        InfoEvent(data={"blob": "attachment://kept"}),
        attachment_lookup={"kept": "payload", "unused": "ignore me"}.get,
    )

    _write_transcript_files(transcript_store, tmp_path)

    assert json.loads((tmp_path / "attachments.json").read_text()) == {
        "kept": "payload"
    }
    assert not (tmp_path / "agent_state.json").exists()


def test_transcript_event_store_warns_for_missing_attachment_ref(
    tmp_path: Path,
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)

    with patch("inspect_ai.log._transcript_store.logger.warning") as warning:
        transcript_store.merge_event(
            InfoEvent(data={"blob": "attachment://missing"}),
            attachment_lookup=_no_attachment,
        )

    warning.assert_called_once_with(
        "Transcript event references missing attachment: %s", "missing"
    )


def test_transcript_event_store_attachment_refs_follow_condense_protocol() -> None:
    from inspect_ai.log._condense import ATTACHMENT_PROTOCOL

    refs = TranscriptEventStore.attachment_refs_from_json(
        json.dumps({"blob": f"{ATTACHMENT_PROTOCOL}kept"})
    )

    assert refs == {"kept"}


def test_transcript_event_store_retains_cumulative_attachments(
    tmp_path: Path,
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)
    first_event = InfoEvent(data={"blob": "attachment://abc"})
    second_event = InfoEvent(data={"blob": "attachment://def"})

    transcript_store.merge_event(first_event, attachment_lookup={"abc": "payload"}.get)
    _write_transcript_files(transcript_store, tmp_path)

    assert json.loads((tmp_path / "attachments.json").read_text()) == {"abc": "payload"}

    transcript_store.merge_event(
        second_event, attachment_lookup={"def": "payload2"}.get
    )
    _write_transcript_files(transcript_store, tmp_path)

    assert json.loads((tmp_path / "attachments.json").read_text()) == {
        "abc": "payload",
        "def": "payload2",
    }


def test_transcript_event_store_retains_attachment_on_event_update(
    tmp_path: Path,
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)
    event = InfoEvent(data={"blob": "attachment://abc"})

    transcript_store.merge_event(event, attachment_lookup={"abc": "payload"}.get)
    event.data = {"blob": "attachment://abc", "status": "done"}
    transcript_store.merge_event(event, attachment_lookup=_no_attachment)
    _write_transcript_files(transcript_store, tmp_path)

    assert json.loads((tmp_path / "attachments.json").read_text()) == {"abc": "payload"}


def test_transcript_event_store_attaches_raw_model_call_update(
    tmp_path: Path,
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)
    event = make_model_event(
        [ChatMessageUser(content="question")],
        call=ModelCall.create(
            {"messages": [{"role": "user", "content": "short"}]}, None
        ),
    )
    transcript_store.merge_event(event, attachment_lookup=_no_attachment)

    raw_payload = "late payload" * 100
    event.call = ModelCall.create(
        {"messages": [{"role": "user", "content": raw_payload}]}, None
    )
    transcript_store.merge_event(event, attachment_lookup=_no_attachment)
    _write_transcript_files(transcript_store, tmp_path)

    attachments = json.loads((tmp_path / "attachments.json").read_text())

    assert raw_payload in attachments.values()
    events_data = json.loads((tmp_path / "events_data.json").read_text())
    call = events_data["calls"][-1]
    assert isinstance(call, dict)
    content = call["content"]
    assert isinstance(content, str)
    assert content.startswith("attachment://")


def test_transcript_event_store_attaches_raw_model_input(
    tmp_path: Path,
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)
    raw_payload = "input payload" * 100

    transcript_store.merge_event(
        make_model_event([ChatMessageUser(content=raw_payload)]),
        attachment_lookup=_no_attachment,
    )
    _write_transcript_files(transcript_store, tmp_path)

    attachments = json.loads((tmp_path / "attachments.json").read_text())
    events_data = json.loads((tmp_path / "events_data.json").read_text())

    assert raw_payload in attachments.values()
    content = events_data["messages"][0]["content"]
    assert isinstance(content, str)
    assert content.startswith("attachment://")


def test_transcript_event_store_exports_stable_message_pool(
    tmp_path: Path,
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)
    sys = ChatMessageSystem(content="sys")
    user = ChatMessageUser(content="question")
    assistant = ChatMessageAssistant(content="answer")

    transcript_store.merge_event(
        make_model_event([sys, user]), attachment_lookup=_no_attachment
    )
    transcript_store.merge_event(
        make_model_event([sys, user, assistant]), attachment_lookup=_no_attachment
    )
    _write_transcript_files(transcript_store, tmp_path)

    events_data = json.loads((tmp_path / "events_data.json").read_text())
    events = json.loads((tmp_path / "events.json").read_text())

    assert len(events_data["messages"]) == 3
    assert events[0]["input_refs"] == [[0, 2]]
    assert events[1]["input_refs"] == [[0, 3]]

    expanded = expand_events(
        (tmp_path / "events.json").read_text(),
        (tmp_path / "events_data.json").read_text(),
    )
    model_events = [event for event in expanded if isinstance(event, ModelEvent)]
    assert [len(event.input) for event in model_events] == [2, 3]


def test_transcript_event_store_merge_pool_entry_returns_canonical_position(
    tmp_path: Path,
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)

    first_pos = transcript_store.merge_message_pool_entry(
        "first-hash", ChatMessageUser(content="first").model_dump_json()
    )
    duplicate_pos = transcript_store.merge_message_pool_entry(
        "first-hash", ChatMessageUser(content="first").model_dump_json()
    )
    second_pos = transcript_store.merge_message_pool_entry(
        "second-hash", ChatMessageUser(content="second").model_dump_json()
    )

    assert first_pos == 0
    assert duplicate_pos == first_pos
    assert second_pos == 1


def test_transcript_event_store_exports_stable_call_pool(tmp_path: Path) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)
    request_message = cast(
        dict[str, JsonValue],
        {"role": "user", "content": "question"},
    )

    transcript_store.merge_event(
        make_model_event(
            [],
            call=ModelCall(
                request={"model": "test", "messages": [request_message]},
                response=None,
            ),
        ),
        attachment_lookup=_no_attachment,
    )
    _write_transcript_files(transcript_store, tmp_path)

    events_data = json.loads((tmp_path / "events_data.json").read_text())
    events = json.loads((tmp_path / "events.json").read_text())

    assert events_data["calls"] == [request_message]
    assert events[0]["call"]["call_refs"] == [[0, 1]]
    assert "messages" not in events[0]["call"]["request"]

    expanded = expand_events(
        (tmp_path / "events.json").read_text(),
        (tmp_path / "events_data.json").read_text(),
    )
    model_events = [event for event in expanded if isinstance(event, ModelEvent)]
    assert model_events[0].call is not None
    assert model_events[0].call.request["messages"] == [request_message]


def test_transcript_event_store_reuses_pending_message_positions_on_update(
    tmp_path: Path,
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)
    message = ChatMessageUser(content="question")
    event = make_model_event([message])
    event.pending = True

    transcript_store.merge_event(event, attachment_lookup=_no_attachment)
    event.pending = False
    transcript_store.merge_event(event, attachment_lookup=_no_attachment)

    assert transcript_store.counts().message_pool == 1


def test_transcript_event_store_discards_pending_cache_on_rollback(
    tmp_path: Path,
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)
    message = ChatMessageUser(content="question")
    event = make_model_event([message])
    event.pending = True

    with patch.object(transcript_store, "_upsert_event", side_effect=RuntimeError):
        try:
            transcript_store.merge_event(event, attachment_lookup=_no_attachment)
        except RuntimeError:
            pass

    retry = make_model_event([message], uuid=event.uuid)
    retry.pending = True
    transcript_store.merge_event(retry, attachment_lookup=_no_attachment)

    assert transcript_store.counts().message_pool == 1


def test_transcript_event_store_deduplicates_messages_using_pool_hash(
    tmp_path: Path,
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)
    first = ChatMessageUser(content="same")
    second = ChatMessageUser(content="same")
    assert first.id != second.id

    transcript_store.merge_event(
        make_model_event([first]), attachment_lookup=_no_attachment
    )
    transcript_store.merge_event(
        make_model_event([second]), attachment_lookup=_no_attachment
    )
    _write_transcript_files(transcript_store, tmp_path)

    events_data = json.loads((tmp_path / "events_data.json").read_text())
    events = json.loads((tmp_path / "events.json").read_text())

    assert len(events_data["messages"]) == 1
    assert events[0]["input_refs"] == [[0, 1]]
    assert events[1]["input_refs"] == [[0, 1]]


def test_transcript_event_store_rejects_events_after_close(tmp_path: Path) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)
    transcript_store.close()

    with pytest.raises(RuntimeError, match="TranscriptEventStore is closed"):
        transcript_store.merge_event(
            InfoEvent(data="late"), attachment_lookup=_no_attachment
        )


def test_transcript_event_store_rejects_pool_import_after_close(
    tmp_path: Path,
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)

    assert (
        transcript_store.merge_message_pool_entry(
            "first-message", ChatMessageUser(content="first").model_dump_json()
        )
        == 0
    )
    assert (
        transcript_store.merge_call_pool_entry(
            "first-call", json.dumps({"role": "user", "content": "first"})
        )
        == 0
    )

    transcript_store.close()

    with pytest.raises(RuntimeError, match="TranscriptEventStore is closed"):
        transcript_store.merge_message_pool_entry(
            "late-message", ChatMessageUser(content="late").model_dump_json()
        )
    with pytest.raises(RuntimeError, match="TranscriptEventStore is closed"):
        transcript_store.merge_call_pool_entry(
            "late-call", json.dumps({"role": "user", "content": "late"})
        )


def test_transcript_event_store_reuses_stored_attachment_on_update(
    tmp_path: Path, caplog
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)
    payload = "payload" * 100
    event = make_model_event([ChatMessageUser(content=payload)])

    transcript_store.merge_event(event, attachment_lookup=_no_attachment)
    transcript_store.merge_event(event, attachment_lookup=_no_attachment)
    _write_transcript_files(transcript_store, tmp_path)

    attachments = json.loads((tmp_path / "attachments.json").read_text())
    assert payload in attachments.values()
    assert "Transcript event references missing attachment" not in caplog.text


def test_transcript_event_store_writes_snapshot_files_as_utf8(
    tmp_path: Path,
) -> None:
    transcript_store = TranscriptEventStore(tmp_path / TRANSCRIPT_EVENT_STORE)
    transcript_store.merge_event(InfoEvent(data="snowman ☃"), _no_attachment)
    _write_transcript_files(transcript_store, tmp_path)

    events = json.loads((tmp_path / "events.json").read_text(encoding="utf-8"))
    assert events[0]["data"] == "snowman ☃"
