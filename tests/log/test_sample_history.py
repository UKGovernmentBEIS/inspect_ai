import sqlite3

import pytest

from inspect_ai._util.json import to_json_str_safe
from inspect_ai.event import InfoEvent, ModelEvent
from inspect_ai.log._log import EvalSample, EventsData
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.model import ChatMessageUser, GenerateConfig, ModelOutput


def _model(uuid: str, completion: str, pending: bool | None = None) -> ModelEvent:
    return ModelEvent(
        uuid=uuid,
        model="mockllm/model",
        input=[ChatMessageUser(id="input-message", content="question")],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
        output=ModelOutput.from_content("mockllm/model", completion),
        pending=pending,
    )


def test_open_sample_history_latest_payload_first_insert_order(tmp_path):
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    first = _model("event-1", "pending", pending=True)
    other = InfoEvent(uuid="event-2", data="middle")
    latest = _model("event-1", "complete", pending=None)

    db.log_events(
        [
            SampleEvent(id="sample", epoch=1, event=first),
            SampleEvent(id="sample", epoch=1, event=other),
            SampleEvent(id="sample", epoch=1, event=latest),
        ]
    )

    with db.open_sample_history("sample", 1) as history:
        rows = history.raw_event_rows

    assert [row.event_id for row in rows] == ["event-1", "event-2"]
    assert rows[0].event["output"]["completion"] == "complete"
    assert rows[0].event.get("pending") is None
    assert rows[1].event["data"] == "middle"


@pytest.mark.parametrize("event_id_literal", ["NULL", "''"])
def test_open_sample_history_blank_event_id_is_unique(tmp_path, event_id_literal):
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    with db._get_connection(write=True) as conn:
        conn.executemany(
            f"""
            INSERT INTO events (event_id, sample_id, sample_epoch, data)
            VALUES ({event_id_literal}, ?, ?, ?)
            """,
            [
                ("sample", 1, to_json_str_safe({"event": "info", "data": "first"})),
                ("sample", 1, to_json_str_safe({"event": "info", "data": "second"})),
            ],
        )

    with db.open_sample_history("sample", 1) as history:
        rows = history.raw_event_rows

    assert [row.event["data"] for row in rows] == ["first", "second"]
    assert len({row.event_id for row in rows}) == 2
    assert all(row.event_id for row in rows)


def test_get_events_synthesizes_missing_event_id(tmp_path):
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    with db._get_connection(write=True) as conn:
        conn.execute(
            """
            INSERT INTO events (event_id, sample_id, sample_epoch, data)
            VALUES (NULL, ?, ?, ?)
            """,
            ("sample", 1, to_json_str_safe({"event": "info", "data": "legacy"})),
        )

        rows = list(db._get_events(conn, "sample", 1))

    assert [row.event["data"] for row in rows] == ["legacy"]
    assert rows[0].event_id


def test_sample_event_count_counts_logical_events_without_materializing_json(tmp_path):
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    with db._get_connection(write=True) as conn:
        conn.executemany(
            """
            INSERT INTO events (event_id, sample_id, sample_epoch, data)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("event-1", "sample", 1, "not json"),
                ("event-1", "sample", 1, "still not json"),
                (None, "sample", 1, "also not json"),
                ("", "sample", 1, "not json either"),
                ("event-other-epoch", "sample", 2, "not json"),
            ],
        )

    assert db.sample_event_count("sample", 1) == 3


def test_sample_history_translates_buffer_pool_refs_to_eval_positions(tmp_path):
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    first = _model("event-1", "first")
    second = _model("event-2", "second")

    db.log_events(
        [
            SampleEvent(id="sample", epoch=1, event=first),
            SampleEvent(id="sample", epoch=1, event=second),
        ]
    )

    with db.open_sample_history("sample", 1) as history:
        events = list(history.iter_events())
        events_data = history.events_data

    sample = EvalSample(
        id="sample",
        epoch=1,
        input="question",
        target="answer",
        events=events,
        events_data=events_data,
    )

    assert isinstance(events_data, dict)
    assert set(events_data.keys()) == set(EventsData.__annotations__.keys())
    model_events = [event for event in sample.events if event.event == "model"]
    assert len(model_events) == 2
    assert model_events[0].input_refs is not None
    assert model_events[1].input_refs is not None
    assert len(events_data["messages"]) == 1
    assert events_data["messages"][0].content == "question"
    assert model_events[0].input_refs == [(0, 1)]
    assert model_events[1].input_refs == [(0, 1)]
    assert all(
        end <= len(sample.events_data["messages"])
        for start, end in model_events[0].input_refs
    )
    assert all(
        end <= len(sample.events_data["messages"])
        for start, end in model_events[1].input_refs
    )


def test_open_sample_history_defers_remove_samples_until_release(tmp_path):
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    db.log_events([SampleEvent(id="sample", epoch=1, event=InfoEvent(data="hello"))])

    with db.open_sample_history("sample", 1) as history:
        db.remove_samples([("sample", 1)])
        assert [event["data"] for event in history.iter_events()] == ["hello"]
        with db._get_connection() as conn:
            assert list(db._get_events(conn, "sample", 1))

    with db._get_connection() as conn:
        assert not list(db._get_events(conn, "sample", 1))


def test_cleanup_defers_while_sample_history_is_open(tmp_path):
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    db.log_events([SampleEvent(id="sample", epoch=1, event=InfoEvent(data="hello"))])

    with db.open_sample_history("sample", 1) as history:
        db.cleanup()
        assert db.db_path.exists()
        assert [event["data"] for event in history.iter_events()] == ["hello"]

    assert not db.db_path.exists()


def test_sample_history_event_rows_are_private(tmp_path):
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    db.log_events([SampleEvent(id="sample", epoch=1, event=_model("event-1", "first"))])

    with db.open_sample_history("sample", 1) as history:
        assert not hasattr(history, "events")
        assert history.raw_event_rows


def test_open_sample_history_releases_write_lock_after_snapshot(tmp_path):
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    db.log_events([SampleEvent(id="sample", epoch=1, event=InfoEvent(data="hello"))])

    with db.open_sample_history("sample", 1) as history:
        conn = sqlite3.connect(db.db_path, timeout=0)
        try:
            conn.execute("PRAGMA busy_timeout=0")
            try:
                conn.execute("BEGIN IMMEDIATE")
                lock_available = True
            except sqlite3.OperationalError as exc:
                assert "locked" in str(exc)
                lock_available = False
        finally:
            conn.close()

        assert lock_available is True
        assert [event["data"] for event in history.iter_events()] == ["hello"]
