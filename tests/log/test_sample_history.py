import sqlite3

import pytest

from inspect_ai._util.json import to_json_str_safe
from inspect_ai.event import InfoEvent, ModelEvent
from inspect_ai.log._log import EvalSample, EventsData
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.streaming import materialize_streaming_sample
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.model import ChatMessageUser, GenerateConfig, ModelCall, ModelOutput


def _model(
    uuid: str,
    completion: str,
    pending: bool | None = None,
    call: ModelCall | None = None,
) -> ModelEvent:
    return ModelEvent(
        uuid=uuid,
        model="mockllm/model",
        input=[ChatMessageUser(id="input-message", content="question")],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
        output=ModelOutput.from_content("mockllm/model", completion),
        pending=pending,
        call=call,
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


def test_open_sample_history_tail_preserves_logical_order(tmp_path):
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
        full_rows = history.raw_event_rows

    with db.open_sample_history_tail("sample", 1, 2) as history:
        tail_rows = history.raw_event_rows

    assert [row.event_id for row in full_rows] == ["event-1", "event-2"]
    assert [row.event_id for row in tail_rows] == ["event-1", "event-2"]
    assert tail_rows[0].event["output"]["completion"] == "complete"
    assert tail_rows[1].event["data"] == "middle"


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


def test_log_events_restores_pool_indices_when_transaction_rolls_back(
    tmp_path, monkeypatch
):
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    event = _model(
        "event-1",
        "answer",
        call=ModelCall(
            request={"messages": [{"role": "user", "content": "question"}]},
            response={},
        ),
    )
    original_condense_event = db._condense_event

    def fail_after_condense(conn, sample_event):
        original_condense_event(conn, sample_event)
        raise RuntimeError("forced rollback")

    monkeypatch.setattr(db, "_condense_event", fail_after_condense)
    with pytest.raises(RuntimeError, match="forced rollback"):
        db.log_events([SampleEvent(id="sample", epoch=1, event=event)])

    monkeypatch.setattr(db, "_condense_event", original_condense_event)
    db.log_events([SampleEvent(id="sample", epoch=1, event=event)])

    with db.open_sample_history("sample", 1) as history:
        assert len(history.message_pool) == 1
        assert len(history.call_pool) == 1
        materialized = materialize_streaming_sample(
            EvalSample(id="sample", epoch=1, input="question", target="answer"),
            history,
        )

    model_event = materialized.events[0]
    assert isinstance(model_event, ModelEvent)
    assert model_event.input_refs is None
    assert model_event.input[0].content == "question"
    assert model_event.call is not None
    assert model_event.call.call_refs is None
    assert model_event.call.request["messages"] == [
        {"role": "user", "content": "question"}
    ]


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


def test_sample_history_read_methods_use_deferred_transactions(
    tmp_path, monkeypatch
) -> None:
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    db.log_events([SampleEvent(id="sample", epoch=1, event=InfoEvent(data="hello"))])

    statements: list[str] = []
    original_connect = sqlite3.connect

    class RecordingConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            statements.append(str(sql))
            return super().execute(sql, *args, **kwargs)

    def connect(*args, **kwargs):
        kwargs["factory"] = RecordingConnection
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)

    assert db.sample_event_count("sample", 1) == 1
    assert db.sample_attachment("sample", 1, "missing") is None
    with db.open_sample_history_tail("sample", 1, 1):
        pass
    with db.open_sample_history_from("sample", 1, 0):
        pass
    with db.open_sample_history("sample", 1):
        pass

    begin_statements = [
        statement.strip().upper()
        for statement in statements
        if statement.strip().upper().startswith("BEGIN")
    ]
    assert begin_statements == ["BEGIN", "BEGIN", "BEGIN", "BEGIN", "BEGIN"]
