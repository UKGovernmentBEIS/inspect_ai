from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection, connect
from threading import RLock
from typing import TextIO

from pydantic import JsonValue
from pydantic_core import to_jsonable_python
from shortuuid import uuid

from inspect_ai._util.hash import mm3_hash
from inspect_ai._util.json import json_dump
from inspect_ai.event._event import Event
from inspect_ai.event._pool import (
    _msg_hash,
    condense_model_event_calls_with_lookup,
    condense_model_event_inputs_with_lookup,
)
from inspect_ai.log._condense import (
    attachment_refs_from_value,
    condense_event,
)
from inspect_ai.model._chat_message import ChatMessage

logger = logging.getLogger(__name__)

CHECKPOINT_EVENT_STORE = "checkpoint_events.sqlite"


@dataclass(frozen=True)
class CheckpointEventStoreCounts:
    events: int
    message_pool: int
    call_pool: int
    attachments: int
    db_bytes: int


class CheckpointEventStore:
    def __init__(self, path: str | Path, *, reset: bool = False) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if reset:
            self._reset_files()
        self._conn = connect(self._path, check_same_thread=False)
        self._lock = RLock()
        self._pending_message_pos_by_event: dict[str, dict[int, int]] = {}
        self._pending_call_pos_by_event: dict[str, dict[int, int]] = {}
        self._conn.row_factory = None
        self._init_schema(self._conn)

    @property
    def path(self) -> Path:
        return self._path

    def counts(self) -> CheckpointEventStoreCounts:
        with self._lock:
            return CheckpointEventStoreCounts(
                events=self._count_rows("events"),
                message_pool=self._count_rows("message_pool"),
                call_pool=self._count_rows("call_pool"),
                attachments=self._count_rows("attachments"),
                db_bytes=self._path.stat().st_size if self._path.exists() else 0,
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def merge_event(
        self, event: Event, attachment_lookup: Callable[[str], str | None]
    ) -> None:
        with self._lock:
            if event.uuid is None:
                event.uuid = uuid()
            logical_id = event.uuid

            with self._conn:
                event_attachments: dict[str, str] = {}
                event = condense_event(event, event_attachments)
                condensed_event = self._condense_event(logical_id, event)
                event_json = json.dumps(
                    to_jsonable_python(
                        condensed_event, exclude_none=True, fallback=lambda _: None
                    ),
                    separators=(",", ":"),
                )
                self._upsert_event(logical_id, event_json)
                self._insert_attachments(event_attachments)
                self._merge_attachment_refs(
                    self._attachment_refs(event),
                    lambda ref: event_attachments.get(ref) or attachment_lookup(ref),
                )

    def merge_condensed_event(
        self,
        logical_id: str,
        event: Mapping[str, JsonValue],
        attachment_lookup: Callable[[str], str | None],
    ) -> None:
        event_jsonable = dict(event)
        event_jsonable.setdefault("uuid", logical_id)
        event_json = json.dumps(event_jsonable, separators=(",", ":"))
        with self._lock:
            with self._conn:
                self._upsert_event(logical_id, event_json)
                self._merge_attachment_refs(
                    attachment_refs_from_value(event_jsonable), attachment_lookup
                )

    def merge_message_pool_entry(self, hash_value: str, json_text: str) -> int:
        with self._lock:
            with self._conn:
                return self._pool_pos("message_pool", hash_value, json_text)

    def merge_message_pool(self, messages: Iterable[ChatMessage]) -> None:
        with self._lock:
            with self._conn:
                for message in messages:
                    self._message_pos(message)

    def merge_call_pool_entry(self, hash_value: str, json_text: str) -> int:
        with self._lock:
            with self._conn:
                return self._pool_pos("call_pool", hash_value, json_text)

    def merge_call_pool(self, calls: Iterable[JsonValue]) -> None:
        with self._lock:
            with self._conn:
                for call in calls:
                    self._call_pos(call)

    def _upsert_event(self, logical_id: str, event_json: str) -> None:
        row = self._conn.execute(
            "SELECT first_seq FROM events WHERE logical_id = ?",
            (logical_id,),
        ).fetchone()
        if row is None:
            first_seq = self._next_event_seq()
            self._conn.execute(
                "INSERT INTO events(logical_id, first_seq, latest_json) VALUES (?, ?, ?)",
                (logical_id, first_seq, event_json),
            )
        else:
            self._conn.execute(
                "UPDATE events SET latest_json = ? WHERE logical_id = ?",
                (event_json, logical_id),
            )

    def _merge_attachment_refs(
        self, refs: Iterable[str], attachment_lookup: Callable[[str], str | None]
    ) -> None:
        for ref in refs:
            content = attachment_lookup(ref)
            if content is not None:
                self._conn.execute(
                    "INSERT OR IGNORE INTO attachments(hash, content) VALUES (?, ?)",
                    (ref, content),
                )
            elif not self._has_attachment(ref):
                logger.warning(
                    "Checkpoint event references missing attachment: %s", ref
                )

    def _has_attachment(self, ref: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM attachments WHERE hash = ?",
            (ref,),
        ).fetchone()
        return row is not None

    def merge_events(
        self, events: Iterable[Event], attachments: Mapping[str, str]
    ) -> None:
        with self._lock:
            for event in events:
                self.merge_event(event, attachments.get)

    def merge_attachments(self, attachments: Mapping[str, str]) -> None:
        if not attachments:
            return
        with self._lock:
            with self._conn:
                self._insert_attachments(attachments)

    def _insert_attachments(self, attachments: Mapping[str, str]) -> None:
        if not attachments:
            return
        self._conn.executemany(
            "INSERT OR IGNORE INTO attachments(hash, content) VALUES (?, ?)",
            attachments.items(),
        )

    def merge_attachment_refs(
        self, refs: Iterable[str], attachment_lookup: Callable[[str], str | None]
    ) -> None:
        with self._lock:
            with self._conn:
                self._merge_attachment_refs(refs, attachment_lookup)

    @staticmethod
    def attachment_refs_from_json(json_text: str) -> set[str]:
        return attachment_refs_from_value(json.loads(json_text))

    def _reset_files(self) -> None:
        for path in (
            self._path,
            self._path.with_name(f"{self._path.name}-wal"),
            self._path.with_name(f"{self._path.name}-shm"),
        ):
            path.unlink(missing_ok=True)

    def export_snapshot_files(
        self,
        sample_working_dir: str | Path,
        *,
        store_json: object,
        agent_state: Mapping[str, object] | None,
    ) -> None:
        sample_dir = Path(sample_working_dir)
        with self._lock:
            self._write_text_atomic(sample_dir / "store.json", json_dump(store_json))
            if agent_state is not None:
                self._write_text_atomic(
                    sample_dir / "agent_state.json", json_dump(agent_state)
                )
            with self._conn:
                self._write_events_data(sample_dir / "events_data.json")
                self._write_json_object_from_rows(
                    sample_dir / "attachments.json",
                    self._conn.execute(
                        "SELECT hash, content FROM attachments ORDER BY hash"
                    ),
                )
                self._write_json_array(
                    sample_dir / "events.json",
                    self._conn.execute(
                        "SELECT latest_json FROM events ORDER BY first_seq"
                    ),
                )

    def _count_rows(self, table: str) -> int:
        row = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        assert row is not None
        return int(row[0])

    def _next_event_seq(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(first_seq), -1) + 1 FROM events"
        ).fetchone()
        assert row is not None
        return int(row[0])

    def _condense_event(self, logical_id: str, event: Event) -> Event:
        message_cache = self._pending_message_pos_by_event.get(logical_id)
        call_cache = self._pending_call_pos_by_event.get(logical_id)
        if event.pending:
            message_cache = message_cache if message_cache is not None else {}
            call_cache = call_cache if call_cache is not None else {}
            self._pending_message_pos_by_event[logical_id] = message_cache
            self._pending_call_pos_by_event[logical_id] = call_cache

        event = condense_model_event_inputs_with_lookup(
            event, lambda message: self._message_pos(message, message_cache)
        )
        event = condense_model_event_calls_with_lookup(
            event, lambda call_message: self._call_pos(call_message, call_cache)
        )
        if not event.pending:
            self._pending_message_pos_by_event.pop(logical_id, None)
            self._pending_call_pos_by_event.pop(logical_id, None)
        return event

    def _message_pos(
        self, message: ChatMessage, cache: dict[int, int] | None = None
    ) -> int:
        message_id = id(message)
        if cache is not None:
            cached_pos = cache.get(message_id)
            if cached_pos is not None:
                return cached_pos

        message_jsonable = to_jsonable_python(
            message,
            exclude_none=True,
            fallback=lambda _: None,
        )
        pos = self._pool_pos(
            "message_pool",
            _msg_hash(message),
            json.dumps(message_jsonable, sort_keys=True),
        )
        if cache is not None:
            cache[message_id] = pos
        return pos

    def _call_pos(
        self, call_message: JsonValue, cache: dict[int, int] | None = None
    ) -> int:
        call_message_id = id(call_message)
        if cache is not None:
            cached_pos = cache.get(call_message_id)
            if cached_pos is not None:
                return cached_pos

        call_json = json.dumps(call_message, sort_keys=True)
        pos = self._pool_pos("call_pool", mm3_hash(call_json), call_json)
        if cache is not None:
            cache[call_message_id] = pos
        return pos

    def _pool_pos(self, table: str, hash_value: str, json_text: str) -> int:
        row = self._conn.execute(
            f"SELECT pos FROM {table} WHERE hash = ?",
            (hash_value,),
        ).fetchone()
        if row is not None:
            return int(row[0])

        pos_row = self._conn.execute(
            f"SELECT COALESCE(MAX(pos), -1) + 1 FROM {table}"
        ).fetchone()
        assert pos_row is not None
        pos = int(pos_row[0])
        self._conn.execute(
            f"INSERT INTO {table}(pos, hash, json) VALUES (?, ?, ?)",
            (pos, hash_value, json_text),
        )
        return pos

    @staticmethod
    def _attachment_refs(event: Event) -> set[str]:
        return attachment_refs_from_value(event.model_dump(mode="python"))

    @staticmethod
    def _write_text_atomic(path: Path, content: str) -> None:
        CheckpointEventStore._write_atomic(path, lambda file: file.write(content))

    @staticmethod
    def _write_json_array(path: Path, rows: Iterable[tuple[str]]) -> None:
        def write(file: TextIO) -> None:
            CheckpointEventStore._write_json_array_to_file(file, rows)
            file.write("\n")

        CheckpointEventStore._write_atomic(path, write)

    @staticmethod
    def _write_json_object_from_rows(
        path: Path, rows: Iterable[tuple[str, str]]
    ) -> None:
        def write(file: TextIO) -> None:
            file.write("{")
            first = True
            for key, value in rows:
                if not first:
                    file.write(",")
                file.write(json.dumps(str(key)))
                file.write(":")
                file.write(json.dumps(value))
                first = False
            file.write("}\n")

        CheckpointEventStore._write_atomic(path, write)

    def _write_events_data(self, path: Path) -> None:
        def write(file: TextIO) -> None:
            file.write('{"messages":')
            self._write_json_array_to_file(
                file,
                self._conn.execute("SELECT json FROM message_pool ORDER BY pos"),
            )
            file.write(',"calls":')
            self._write_json_array_to_file(
                file,
                self._conn.execute("SELECT json FROM call_pool ORDER BY pos"),
            )
            file.write("}\n")

        self._write_atomic(path, write)

    @staticmethod
    def _write_atomic(path: Path, write: Callable[[TextIO], object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            text=True,
        )
        tmp_path = Path(tmp_name)
        try:
            with open(fd, "w") as file:
                write(file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp_path, path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _write_json_array_to_file(file: TextIO, rows: Iterable[tuple[str]]) -> None:
        file.write("[")
        first = True
        for (json_text,) in rows:
            if not first:
                file.write(",")
            file.write(str(json_text))
            first = False
        file.write("]")

    @staticmethod
    def _init_schema(conn: Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                logical_id TEXT PRIMARY KEY,
                first_seq INTEGER NOT NULL UNIQUE,
                latest_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS message_pool (
                pos INTEGER PRIMARY KEY,
                hash TEXT NOT NULL UNIQUE,
                json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS call_pool (
                pos INTEGER PRIMARY KEY,
                hash TEXT NOT NULL UNIQUE,
                json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS attachments (
                hash TEXT PRIMARY KEY,
                content TEXT NOT NULL
            );
            """
        )
        conn.commit()
