import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from sqlite3 import Connection
from typing import Any, Iterator, TypeAlias, cast

from pydantic import BaseModel, JsonValue

from inspect_ai._util.appdirs import inspect_data_dir

from .._transcript import Event
from .types import SampleSummary

JsonData: TypeAlias = dict[str, JsonValue]


# partial events
# attachments


class SampleInfo(BaseModel):
    id: str
    epoch: int
    sample: SampleSummary | None


class EventInfo(BaseModel):
    id: int
    sample_id: str
    epoch: int
    event: JsonData


class SampleEventDatabase:
    SCHEMA = """

    CREATE TABLE samples (
        id TEXT,
        epoch INTEGER,
        data TEXT, -- JSON containing all other sample fields
        PRIMARY KEY (id, epoch)
    );

    CREATE TABLE events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sample_id TEXT,
        sample_epoch INTEGER,
        data TEXT, -- JSON containing full event
        FOREIGN KEY (sample_id, sample_epoch) REFERENCES samples(id, epoch)
    );

    -- Indices for foreign keys and common queries
    CREATE INDEX IF NOT EXISTS idx_events_sample ON events(sample_id, sample_epoch);
    """

    def __init__(self, location: str, db_dir: Path | None = None):
        self.location = location

        # provide default db dir
        if db_dir is None:
            db_dir = inspect_data_dir("eventdb")

        self.db_path = db_dir / hashlib.sha256(location.encode("utf-8")).hexdigest()
        self._initialize_db()

    def _initialize_db(self) -> None:
        """Initialize the database schema."""
        with self._get_connection() as conn:
            conn.executescript(self.SCHEMA)
            conn.commit()

    @contextmanager
    def _get_connection(self) -> Iterator[Connection]:
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable row factory for named columns
        try:
            # Enable foreign key constraints
            conn.execute("PRAGMA foreign_keys = ON")

            yield conn
            conn.commit()  # Auto-commit if no exceptions
        except Exception:
            conn.rollback()  # Auto-rollback on any error
            raise
        finally:
            conn.close()

    def start_sample(self, sample: SampleSummary) -> int:
        """Start logging a sample. Returns the internal sample_id."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO samples (id, epoch, data)
                VALUES (?, ?, ?)
                RETURNING id
            """,
                (str(sample.id), sample.epoch, sample.model_dump_json()),
            )
            return cast(int, cursor.fetchone()[0])

    def log_events(self, id: int | str, epoch: int, events: list[Event]) -> list[int]:
        with self._get_connection() as conn:
            # Collect the values for all events
            values: list[Any] = []
            for event in events:
                values.extend((id, epoch, event.model_dump_json()))

            # Dynamically create the SQL query
            placeholders = ", ".join(["(?, ?, ?)"] * len(events))
            sql = f"""
            INSERT INTO events (sample_id, sample_epoch, data)
            VALUES {placeholders}
            """

            # Insert all rows
            conn.execute(sql, values)

            # Fetch the last inserted IDs
            cursor = conn.execute(
                "SELECT id FROM events ORDER BY id DESC LIMIT ?", (len(events),)
            )
            event_ids = [row[0] for row in cursor.fetchall()][
                ::-1
            ]  # Reverse order to match insertion
            return event_ids

    def complete_sample(self, summary: SampleSummary) -> str | int:
        """Note that a sample has completed processing. Returns the internal summary_id."""
        with self._get_connection() as conn:
            # Then insert the summary
            cursor = conn.execute(
                """
                UPDATE samples SET data = ? WHERE id = ? and epoch = ?
            """,
                (summary.model_dump_json(), summary.id, summary.epoch),
            )

            if cursor.rowcount == 0:
                raise ValueError("No rows were updated. Matching row not found.")

            return summary.id

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

    def get_samples(self) -> Iterator[SampleInfo]:
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
                summary = row["sample_data"]
                yield SampleInfo(
                    id=id,
                    epoch=epoch,
                    sample=SampleSummary.model_validate_json(summary),
                )

    def get_events(
        self,
        id: str | int,
        epoch: int,
        after_event_id: int | None = None,
    ) -> Iterator[EventInfo]:
        if id is not None and epoch is None:
            raise ValueError("If id is provided, epoch must also be provided")

        with self._get_connection() as conn:
            query = """
                SELECT id, sample_id, sample_epoch, data
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
                yield EventInfo(
                    id=row["id"],
                    sample_id=row["sample_id"],
                    epoch=row["sample_epoch"],
                    event=event,
                )

    def cleanup(self) -> None:
        try:
            os.remove(self.db_path)
        except FileNotFoundError:
            pass
