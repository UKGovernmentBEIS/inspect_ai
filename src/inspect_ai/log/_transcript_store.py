from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection, connect
from threading import RLock
from typing import TextIO

from pydantic import JsonValue
from pydantic_core import to_jsonable_python
from shortuuid import uuid

from inspect_ai._util.file import write_atomic_text
from inspect_ai.event import (
    _pool,  # accessed as module attributes so monkeypatching _pool hashes is visible here
)
from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._pool_index import (
    CallPoolIndex,
    MessagePoolIndex,
    condense_model_event_with_indices,
)
from inspect_ai.log._condense import (
    WalkContext,
    attachment_refs_from_value,
    condense_event,
    events_attachment_fn,
    walk_chat_message,
    walk_json_value,
)
from inspect_ai.model._chat_message import ChatMessage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscriptEventStoreCounts:
    events: int
    message_pool: int
    call_pool: int
    attachments: int
    db_bytes: int


class TranscriptEventStore:
    """Incrementally accumulates transcript event state.

    The live transcript may evict old resident events in bounded mode, so this
    SQLite-backed store keeps a complete event stream with pooled model inputs,
    pooled model calls, and retained attachment payloads. Consumers can merge
    live or condensed events and export transcript-owned JSON artifacts.
    """

    def __init__(self, path: str | Path, *, reset: bool = False) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if reset:
            self._reset_files()
        self._conn = connect(self._path, check_same_thread=False)
        self._lock = RLock()
        # one store per sample transcript; full pool state lives in SQLite,
        # and the in-memory indices are seeded from existing rows below so a
        # reopened store dedups re-sent history against them
        self._msg_pool_index = MessagePoolIndex()
        self._call_pool_index = CallPoolIndex()
        self._merge_cursors: dict[str, int] = {"message_pool": 0, "call_pool": 0}
        self._conn.row_factory = None
        self._closed = False
        self._init_schema(self._conn)
        # Reopened stores have rows the empty in-memory indices don't know
        # about; seed hash lookup state (first occurrence per hash) so the
        # break path dedups re-sent history against existing rows. The
        # condense callbacks insert unconditionally (the helper owns dedup),
        # so without this seeding every reopen would duplicate re-sent
        # history rows.
        for pos, hash_value in self._conn.execute(
            "SELECT pos, hash FROM message_pool ORDER BY pos"
        ):
            self._msg_pool_index.add_hash_only(str(hash_value), int(pos))
        for pos, hash_value in self._conn.execute(
            "SELECT pos, hash FROM call_pool ORDER BY pos"
        ):
            self._call_pool_index.add_hash(str(hash_value), int(pos), new_entry=False)

    @property
    def path(self) -> Path:
        return self._path

    def counts(self) -> TranscriptEventStoreCounts:
        with self._lock:
            self._ensure_open()
            return TranscriptEventStoreCounts(
                events=self._count_rows("events"),
                message_pool=self._count_rows("message_pool"),
                call_pool=self._count_rows("call_pool"),
                attachments=self._count_rows("attachments"),
                db_bytes=self._path.stat().st_size if self._path.exists() else 0,
            )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("TranscriptEventStore is closed")

    def merge_event(
        self, event: Event, attachment_lookup: Callable[[str], str | None]
    ) -> None:
        with self._lock:
            self._ensure_open()
            if event.uuid is None:
                event.uuid = uuid()
            logical_id = event.uuid

            msg_mark = self._msg_pool_index.mark()
            call_mark = self._call_pool_index.mark()
            try:
                with self._conn:
                    event_attachments: dict[str, str] = {}
                    incoming_refs: set[str] = set()
                    if isinstance(event, ModelEvent):
                        condensed_event: Event = self._condense_model_event(
                            event, event_attachments, incoming_refs
                        )
                    else:
                        condensed_event = condense_event(event, event_attachments)
                        incoming_refs.update(self._attachment_refs(condensed_event))
                    event_json = json.dumps(
                        to_jsonable_python(
                            condensed_event, exclude_none=True, fallback=lambda _: None
                        ),
                        separators=(",", ":"),
                    )
                    self._upsert_event(logical_id, event_json)
                    self._insert_attachments(event_attachments)
                    self._merge_attachment_refs(
                        incoming_refs,
                        lambda ref: event_attachments.get(ref)
                        or attachment_lookup(ref),
                    )
            except BaseException:
                # the SQLite transaction rolled back; unwind the in-memory
                # indices so they don't reference rolled-back pool rows
                self._msg_pool_index.restore(msg_mark)
                self._call_pool_index.restore(call_mark)
                raise

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
            self._ensure_open()
            with self._conn:
                self._upsert_event(logical_id, event_json)
                self._merge_attachment_refs(
                    attachment_refs_from_value(event_jsonable), attachment_lookup
                )

    def _merge_pool_entry(
        self, table: str, hash_value: str, json_text: str, *, dedup: bool = False
    ) -> int:
        """Merge one entry of a position-ordered pool list.

        Positional-prefix semantics: sequential calls walk the existing
        table from pos 0 via a per-table cursor. A hash match at the
        cursor reuses that row (so re-seeding the same pool list is
        idempotent and position-preserving); otherwise the entry is
        appended — or, with ``dedup=True``, first looked up by hash
        anywhere in the table.

        ``dedup=False`` (hydration seeding): merged condensed events keep
        their refs verbatim, so positions must round-trip exactly; a
        hash-keyed merge would collapse occurrence rows (equal-content
        rows at distinct positions), shifting every later position and
        corrupting those refs.

        ``dedup=True`` (buffer export): the caller remaps refs through the
        returned positions, so cross-boundary hash dedup is safe — and
        needed, because export runs after seeding and the buffer's
        re-condensed history would otherwise duplicate every seeded row.

        The cursor is not rewound on transaction rollback. That is safe:
        a stale cursor pointing past the rolled-back row misses the
        positional match and falls through to append / ``dedup`` lookup,
        which never returns a wrong position — the cost is one skipped
        cursor-match, not corruption. (``merge_message_pool`` /
        ``merge_call_pool`` additionally reset the cursor to 0 on entry.)
        """
        cursor = self._merge_cursors[table]
        row = self._conn.execute(
            f"SELECT hash FROM {table} WHERE pos = ?", (cursor,)
        ).fetchone()
        if row is not None and str(row[0]) == hash_value:
            pos = cursor
        elif dedup:
            pos = self._pool_pos(table, hash_value, json_text)
        else:
            pos = self._pool_append(table, hash_value, json_text)
        self._merge_cursors[table] = pos + 1
        return pos

    def merge_message_pool_entry(self, hash_value: str, json_text: str) -> int:
        with self._lock:
            self._ensure_open()
            with self._conn:
                pos = self._merge_pool_entry(
                    "message_pool", hash_value, json_text, dedup=True
                )
                # the live condense path dedups in memory only, so exported
                # rows must be registered here or a later live merge of
                # equal content would duplicate them
                self._msg_pool_index.add_hash_only(hash_value, pos)
                return pos

    def merge_message_pool(self, messages: Iterable[ChatMessage]) -> None:
        with self._lock:
            self._ensure_open()
            mark = self._msg_pool_index.mark()
            try:
                with self._conn:
                    # full position-ordered pool list: walk from pos 0 so
                    # re-seeding the same list is idempotent
                    self._merge_cursors["message_pool"] = 0
                    positions: list[int] = []
                    msgs: list[ChatMessage] = []
                    for message in messages:
                        hash_value = _pool._msg_hash(message)
                        pos = self._merge_pool_entry(
                            "message_pool",
                            hash_value,
                            _pool._msg_pool_json(_pool._msg_pool_jsonable(message)),
                        )
                        # registered even on a cursor hit: resume-pool objects
                        # recur across the seeding pass, so pinning them earns
                        # identity hits
                        self._msg_pool_index.add(
                            message, hash_value, pos, new_entry=False
                        )
                        positions.append(pos)
                        msgs.append(message)
                    # seed prefix state: the first post-resume event re-sends
                    # this history; matching it as a prefix keeps positions
                    # monotone instead of hash-mapping occurrence rows back
                    # to first positions. Best-effort: hydrated pools are
                    # walked-form while live inputs are pre-walk, so on any
                    # mismatch the break path runs (correct, just not
                    # single-range for that one event).
                    if msgs:
                        self._msg_pool_index.set_prev(msgs, positions)
            except BaseException:
                self._msg_pool_index.restore(mark)
                raise

    def merge_call_pool_entry(self, hash_value: str, json_text: str) -> int:
        with self._lock:
            self._ensure_open()
            with self._conn:
                pos = self._merge_pool_entry(
                    "call_pool", hash_value, json_text, dedup=True
                )
                self._call_pool_index.add_hash(hash_value, pos, new_entry=False)
                return pos

    def merge_call_pool(self, calls: Iterable[JsonValue]) -> None:
        with self._lock:
            self._ensure_open()
            mark = self._call_pool_index.mark()
            try:
                with self._conn:
                    self._merge_cursors["call_pool"] = 0
                    positions: list[int] = []
                    call_list: list[JsonValue] = []
                    for call in calls:
                        hash_value = _pool._call_hash(call)
                        pos = self._merge_pool_entry(
                            "call_pool",
                            hash_value,
                            _pool._call_pool_json(call),
                        )
                        self._call_pool_index.add_hash(hash_value, pos, new_entry=False)
                        positions.append(pos)
                        call_list.append(call)
                    if call_list:
                        self._call_pool_index.set_prev(call_list, positions)
            except BaseException:
                self._call_pool_index.restore(mark)
                raise

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
                    "Transcript event references missing attachment: %s", ref
                )

    def _has_attachment(self, ref: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM attachments WHERE hash = ?",
            (ref,),
        ).fetchone()
        return row is not None

    def attachment(self, ref: str) -> str | None:
        with self._lock:
            self._ensure_open()
            row = self._conn.execute(
                "SELECT content FROM attachments WHERE hash = ?",
                (ref,),
            ).fetchone()
            return str(row[0]) if row is not None else None

    def has_event(self, logical_id: str) -> bool:
        with self._lock:
            self._ensure_open()
            row = self._conn.execute(
                "SELECT 1 FROM events WHERE logical_id = ?",
                (logical_id,),
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
            self._ensure_open()
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
            self._ensure_open()
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

    def write_transcript_files(
        self,
        *,
        events_path: str | Path,
        events_data_path: str | Path,
        attachments_path: str | Path,
    ) -> None:
        with self._lock:
            self._ensure_open()
            with self._conn:
                self._write_events_data(Path(events_data_path))
                self._write_json_object_from_rows(
                    Path(attachments_path),
                    self._conn.execute(
                        "SELECT hash, content FROM attachments ORDER BY hash"
                    ),
                )
                self._write_json_array(
                    Path(events_path),
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

    def _condense_model_event(
        self,
        event: ModelEvent,
        event_attachments: dict[str, str],
        incoming_refs: set[str],
    ) -> Event:
        """Condense a ModelEvent against the in-memory pool indices.

        Pool dedup walks/serializes only messages new to the pool; attachment
        refs are collected from new pool entries plus the walked remainder
        (input emptied, call request without messages), so the per-event ref
        scan is O(event-own-content) rather than O(history).

        Args:
            event: The model event to condense.
            event_attachments: Out-parameter — attachment content produced by
                walking is added here (mutated via the walk closures).
            incoming_refs: Out-parameter — attachment refs from new pool
                entries and the walked remainder are added here.

        Returns:
            The condensed event (input/call request replaced by pool refs).
        """
        content_fn = events_attachment_fn(event_attachments)
        context = WalkContext(message_cache={}, only_core=False)

        # the callbacks append unconditionally: the helper has already made
        # the dedup decision when it calls back (occurrence row on pure
        # append, hash dedup on a break). A hash-keyed lookup here would
        # collapse occurrence rows back onto their first positions and
        # disagree with what set_prev records. Safe across reopen because
        # __init__ seeds the in-memory hash indices from existing rows.
        def add_message(hash_value: str, walked: ChatMessage) -> int:
            message_jsonable = _pool._msg_pool_jsonable(walked)
            incoming_refs.update(attachment_refs_from_value(message_jsonable))
            return self._pool_append(
                "message_pool",
                hash_value,
                _pool._msg_pool_json(message_jsonable),
            )

        def add_call(hash_value: str, walked: JsonValue) -> int:
            incoming_refs.update(attachment_refs_from_value(walked))
            return self._pool_append(
                "call_pool", hash_value, _pool._call_pool_json(walked)
            )

        condensed = condense_model_event_with_indices(
            event,
            messages=self._msg_pool_index,
            calls=self._call_pool_index,
            walk_message=lambda m: walk_chat_message(m, content_fn, context),
            walk_call_message=lambda v: walk_json_value(v, content_fn, context),
            add_message=add_message,
            add_call=add_call,
        )

        # walk the remainder (input now [], call request without messages)
        condensed_remainder = condense_event(
            condensed, event_attachments, context=context
        )
        incoming_refs.update(self._attachment_refs(condensed_remainder))
        return condensed_remainder

    def _pool_append(self, table: str, hash_value: str, json_text: str) -> int:
        """Insert a new pool row at the next position, unconditionally.

        The condense helper owns dedup decisions (occurrence rows on pure
        append, hash dedup on a break); this storage primitive never
        second-guesses them.
        """
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

    def _pool_pos(self, table: str, hash_value: str, json_text: str) -> int:
        """Position of the first row with this hash, inserting if absent.

        ``MIN(pos)`` makes the first occurrence the canonical dedup target,
        deterministically, now that equal-content rows can coexist.
        """
        row = self._conn.execute(
            f"SELECT MIN(pos) FROM {table} WHERE hash = ?",
            (hash_value,),
        ).fetchone()
        if row is not None and row[0] is not None:
            return int(row[0])
        return self._pool_append(table, hash_value, json_text)

    @staticmethod
    def _attachment_refs(event: Event) -> set[str]:
        return attachment_refs_from_value(event.model_dump(mode="python"))

    @staticmethod
    def _write_json_array(path: Path, rows: Iterable[tuple[str]]) -> None:
        def write(file: TextIO) -> None:
            TranscriptEventStore._write_json_array_to_file(file, rows)
            file.write("\n")

        TranscriptEventStore._write_atomic(path, write)

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

        TranscriptEventStore._write_atomic(path, write)

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
        write_atomic_text(path, write)

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
                hash TEXT NOT NULL,
                json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_message_pool_hash
                ON message_pool(hash);

            CREATE TABLE IF NOT EXISTS call_pool (
                pos INTEGER PRIMARY KEY,
                hash TEXT NOT NULL,
                json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_call_pool_hash
                ON call_pool(hash);

            CREATE TABLE IF NOT EXISTS attachments (
                hash TEXT PRIMARY KEY,
                content TEXT NOT NULL
            );
            """
        )
        for table in ("message_pool", "call_pool"):
            TranscriptEventStore._migrate_unique_hash(conn, table)
        conn.commit()

    @staticmethod
    def _migrate_unique_hash(conn: Connection, table: str) -> None:
        """Rebuild a pool table created by pre-occurrence-row code.

        Old stores declared ``hash TEXT NOT NULL UNIQUE``; occurrence rows
        require duplicate hashes. SQLite can't drop a column constraint in
        place, so detect the inline UNIQUE in the table SQL and rebuild.
        Positions (``pos``) are preserved exactly, so refs in stored events
        remain valid.
        """
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if row is None or "UNIQUE" not in str(row[0]).upper():
            return
        # explicit BEGIN/COMMIT: executescript runs in autocommit otherwise,
        # and a crash between RENAME and DROP would strand a {table}_old
        # orphan holding a duplicate of every pool row
        conn.executescript(
            f"""
            BEGIN;
            ALTER TABLE {table} RENAME TO {table}_old;
            CREATE TABLE {table} (
                pos INTEGER PRIMARY KEY,
                hash TEXT NOT NULL,
                json TEXT NOT NULL
            );
            INSERT INTO {table}(pos, hash, json)
                SELECT pos, hash, json FROM {table}_old;
            DROP TABLE {table}_old;
            CREATE INDEX IF NOT EXISTS idx_{table}_hash ON {table}(hash);
            COMMIT;
            """
        )
