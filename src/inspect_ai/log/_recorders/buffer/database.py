import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from logging import getLogger
from pathlib import Path
from sqlite3 import Connection
from typing import Any, Callable, Iterator

import psutil
from typing_extensions import override

from inspect_ai._util.appdirs import inspect_data_dir

from ..._condense import (
    ATTACHMENT_PROTOCOL,
    attachments_content_fn,
    walk_events,
    walk_input,
    walk_json_dict,
)
from ..._transcript import Event
from ..types import SampleSummary
from .types import AttachmentInfo, EventInfo, JsonData, SampleBuffer, SampleInfo

logger = getLogger(__name__)


class SampleBufferDatabase(SampleBuffer):
    SCHEMA = """

    CREATE TABLE samples (
        id TEXT,
        epoch INTEGER,
        data TEXT, -- JSON containing all other sample fields
        PRIMARY KEY (id, epoch)
    );

    CREATE TABLE events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT,
        sample_id TEXT,
        sample_epoch INTEGER,
        data TEXT, -- JSON containing full event
        FOREIGN KEY (sample_id, sample_epoch) REFERENCES samples(id, epoch)
    );

    CREATE TABLE attachments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hash TEXT UNIQUE,
        content TEXT
    );

    -- Indices for foreign keys and common queries
    CREATE INDEX IF NOT EXISTS idx_events_sample ON events(sample_id, sample_epoch);
    CREATE INDEX IF NOT EXISTS idx_attachments_hash ON attachments(hash);
    """

    def __init__(
        self, location: str, log_images: bool = True, db_dir: Path | None = None
    ):
        self.location = location
        self.log_images = log_images

        # set path
        db_dir = resolve_db_dir(db_dir)
        self.db_path = (
            db_dir / f"{hashlib.sha256(location.encode()).hexdigest()}.{os.getpid()}.db"
        )

        # initialize the database schema
        with self._get_connection() as conn:
            conn.executescript(self.SCHEMA)
            conn.commit()

    def start_sample(self, sample: SampleSummary) -> None:
        with self._get_connection() as conn:
            sample = self._consense_sample(conn, sample)
            conn.execute(
                """
                INSERT INTO samples (id, epoch, data)
                VALUES (?, ?, ?)
            """,
                (str(sample.id), sample.epoch, sample.model_dump_json()),
            )

    def log_events(self, id: int | str, epoch: int, events: list[Event]) -> None:
        with self._get_connection() as conn:
            # Collect the values for all events
            events = self._consense_events(conn, events)
            values: list[Any] = []
            for event in events:
                values.extend((event._id, id, epoch, event.model_dump_json()))

            # Dynamically create the SQL query
            placeholders = ", ".join(["(?, ?, ?, ?)"] * len(events))
            sql = f"""
            INSERT INTO events (event_id, sample_id, sample_epoch, data)
            VALUES {placeholders}
            """

            # Insert all rows
            conn.execute(sql, values)

    def complete_sample(self, summary: SampleSummary) -> None:
        with self._get_connection() as conn:
            summary = self._consense_sample(conn, summary)
            conn.execute(
                """
                UPDATE samples SET data = ? WHERE id = ? and epoch = ?
            """,
                (summary.model_dump_json(), str(summary.id), summary.epoch),
            )

    def remove_samples(self, samples: list[tuple[str | int, int]]) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Convert list of tuples into a string for SQL IN clause
            # Format: (('id1', 1), ('id2', 2))
            sample_conditions = ",".join(
                [f"('{sid}', {epoch})" for sid, epoch in samples]
            )

            # Delete associated events first due to foreign key constraint
            events_query = f"""
                DELETE FROM events
                WHERE (sample_id, sample_epoch) IN ({sample_conditions})
            """
            cursor.execute(events_query)

            # Then delete the samples
            samples_query = f"""
                DELETE FROM samples
                WHERE (id, epoch) IN ({sample_conditions})
            """
            cursor.execute(samples_query)

    @override
    def get_samples(self, resolve_attachments: bool = True) -> Iterator[SampleInfo]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT s.id as sample_id, s.epoch as sample_epoch, s.data as sample_data
                FROM samples s
                ORDER BY s.id
            """
            )

            for row in cursor:
                id = row["sample_id"]
                epoch = row["sample_epoch"]
                summary = SampleSummary.model_validate_json(row["sample_data"])
                if resolve_attachments:
                    summary = self._resolve_sample_attachments(conn, summary)
                yield SampleInfo(
                    id=id,
                    epoch=epoch,
                    sample=summary,
                )

    @override
    def get_events(
        self,
        id: str | int,
        epoch: int,
        after_event_id: int | None = None,
        resolve_attachments: bool = True,
    ) -> Iterator[EventInfo]:
        if id is not None and epoch is None:
            raise ValueError("If id is provided, epoch must also be provided")

        with self._get_connection() as conn:
            query = """
                SELECT id, event_id, sample_id, sample_epoch, data
                FROM events e WHERE sample_id = ? AND sample_epoch = ?
            """
            params: list[str | int] = [str(id), epoch]

            if after_event_id is not None:
                query += " AND e.id > ?"
                params.append(after_event_id)

            query += " ORDER BY e.id"

            cursor = conn.execute(query, params)

            for row in cursor:
                event = json.loads(row["data"])
                if resolve_attachments:
                    event = self._resolve_event_attachments(conn, event)
                yield EventInfo(
                    id=row["id"],
                    event_id=row["event_id"],
                    sample_id=row["sample_id"],
                    epoch=row["sample_epoch"],
                    event=event,
                )

    @override
    def get_attachments(
        self, after_attachment_id: int | None = None
    ) -> Iterator[AttachmentInfo]:
        with self._get_connection() as conn:
            query = """
                SELECT id, hash, content FROM attachments
            """
            params: list[str | int] = []

            if after_attachment_id is not None:
                query += " WHERE id > ?"
                params.append(after_attachment_id)

            cursor = conn.execute(query, params)

            for row in cursor:
                yield AttachmentInfo(
                    id=row["id"], hash=row["hash"], content=row["content"]
                )

    @override
    def get_attachments_content(self, hashes: list[str]) -> dict[str, str | None]:
        with self._get_connection() as conn:
            return self._get_attachments_content(conn, hashes)

    def cleanup(self) -> None:
        cleanup_sample_buffer_db(self.db_path)

    @contextmanager
    def _get_connection(self) -> Iterator[Connection]:
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row  # Enable row factory for named columns
        try:
            # Enable foreign key constraints
            conn.execute("PRAGMA foreign_keys = ON")

            # concurrency setup
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA synchronous=NORMAL")

            yield conn
            conn.commit()  # Auto-commit if no exceptions
        except Exception:
            conn.rollback()  # Auto-rollback on any error
            raise
        finally:
            conn.close()

    def _consense_sample(
        self, conn: Connection, sample: SampleSummary
    ) -> SampleSummary:
        # alias attachments
        attachments: dict[str, str] = {}
        sample = sample.model_copy(
            update={
                "input": walk_input(
                    sample.input, self._create_attachments_content_fn(attachments)
                )
            }
        )

        # insert attachments
        self._insert_attachments(conn, attachments)

        # return sample with aliases
        return sample

    def _resolve_sample_attachments(
        self, conn: Connection, sample: SampleSummary
    ) -> SampleSummary:
        return sample.model_copy(
            update={
                "input": walk_input(
                    sample.input, self._resolve_attachments_content_fn(conn)
                )
            }
        )

    def _consense_events(self, conn: Connection, events: list[Event]) -> list[Event]:
        # alias attachments
        attachments: dict[str, str] = {}
        events = walk_events(events, self._create_attachments_content_fn(attachments))

        # insert attachments
        self._insert_attachments(conn, attachments)

        # return events with aliases
        return events

    def _resolve_event_attachments(self, conn: Connection, event: JsonData) -> JsonData:
        return walk_json_dict(event, self._resolve_attachments_content_fn(conn))

    def _create_attachments_content_fn(
        self, attachments: dict[str, str]
    ) -> Callable[[str], str]:
        return attachments_content_fn(self.log_images, 100, attachments)

    def _resolve_attachments_content_fn(self, conn: Connection) -> Callable[[str], str]:
        def content_fn(text: str) -> str:
            if text.startswith(ATTACHMENT_PROTOCOL):
                hash = text.replace(ATTACHMENT_PROTOCOL, "", 1)
                attachments = self._get_attachments_content(conn, [hash])
                content = attachments.get(hash, None)
                if content is not None:
                    return content
                else:
                    return text
            else:
                return text

        return content_fn

    def _insert_attachments(
        self, conn: Connection, attachments: dict[str, str]
    ) -> None:
        conn.executemany(
            """
            INSERT OR IGNORE INTO attachments (hash, content)
            VALUES (?, ?)
            """,
            attachments.items(),
        )

    def _get_attachments_content(
        self, conn: Connection, hashes: list[str]
    ) -> dict[str, str | None]:
        # Create placeholders for the IN clause
        placeholders = ",".join("?" * len(hashes))

        cursor = conn.execute(
            f"""
            SELECT hash, content
            FROM attachments
            WHERE hash IN ({placeholders})
            """,
            hashes,
        )

        # Create result dictionary with all requested hashes initialized to None
        results: dict[str, str | None] = {hash_: None for hash_ in hashes}

        # Update with found values
        for row in cursor:
            results[row["hash"]] = row["content"]

        return results


def cleanup_sample_buffer_databases(db_dir: Path | None = None) -> None:
    db_dir = resolve_db_dir(db_dir)
    for db in db_dir.glob("*.*.db"):
        _, pid_str, _ = db.name.rsplit(".", 2)
        if pid_str.isdigit():
            pid = int(pid_str)
            if not psutil.pid_exists(pid):
                cleanup_sample_buffer_db(db)


def cleanup_sample_buffer_db(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception as ex:
        logger.warning(f"Error cleaning up sample buffer database at {path}: {ex}")


def resolve_db_dir(db_dir: Path | None = None) -> Path:
    return db_dir or inspect_data_dir("samplebuffer")
