import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from sqlite3 import Connection
from typing import Iterator, TypeAlias, cast

from pydantic import BaseModel, JsonValue

from .._log import EvalSample

JsonData: TypeAlias = dict[str, JsonValue]


class SampleInfo(BaseModel):
    id: str
    epoch: int
    sample: EvalSample
    summary: JsonData | None


class EventInfo(BaseModel):
    id: int
    sample_id: str
    epoch: int
    event: JsonData


class SampleEventDatabase:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS samples (
        sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
        location TEXT,
        id TEXT,
        epoch INTEGER,
        data TEXT,  -- JSON containing all other sample fields
        UNIQUE(location, id, epoch)
    );

    CREATE TABLE IF NOT EXISTS events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sample_id INTEGER,
        data TEXT,  -- JSON containing full event
        FOREIGN KEY (sample_id) REFERENCES samples(sample_id)
    );

    CREATE TABLE IF NOT EXISTS sample_summaries (
        summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sample_id INTEGER UNIQUE,  -- one summary per sample
        data TEXT,  -- JSON containing full summary
        FOREIGN KEY (sample_id) REFERENCES samples(sample_id)
    );

    -- Indices for foreign keys and common queries
    CREATE INDEX IF NOT EXISTS idx_samples_location ON samples(location);
    CREATE INDEX IF NOT EXISTS idx_samples_composite ON samples(location, id, epoch);
    CREATE INDEX IF NOT EXISTS idx_events_sample ON events(sample_id);
    CREATE INDEX IF NOT EXISTS idx_events_id ON events(event_id);
    """

    def __init__(self, location: str, db_dir: str = tempfile.mkdtemp()):
        self.location = location
        self.db_path = os.path.join(
            db_dir, hashlib.sha256(location.encode("utf-8")).hexdigest()
        )
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
            yield conn
            conn.commit()  # Auto-commit if no exceptions
        except Exception:
            conn.rollback()  # Auto-rollback on any error
            raise
        finally:
            conn.close()

    def start_sample(self, sample: EvalSample) -> int:
        """Start logging a sample. Returns the internal sample_id."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO samples (location, id, epoch, data)
                VALUES (?, ?, ?, ?)
                RETURNING sample_id
            """,
                (self.location, str(sample.id), sample.epoch, sample.model_dump_json()),
            )
            return cast(int, cursor.fetchone()[0])

    def log_events(
        self, id: int | str, epoch: int, events: list[JsonData]
    ) -> list[int]:
        if not events:
            return []

        with self._get_connection() as conn:
            # First get the sample_id
            cursor = conn.execute(
                """
                SELECT sample_id
                FROM samples
                WHERE location = ? AND id = ? AND epoch = ?
            """,
                (self.location, str(id), epoch),
            )

            row = cursor.fetchone()
            if not row:
                raise ValueError(f"No sample found for id={id}, epoch={epoch}")

            sample_id = row[0]

            # Execute inserts one at a time to get event_ids
            event_ids = []
            for event in events:
                cursor = conn.execute(
                    """
                    INSERT INTO events (sample_id, data)
                    VALUES (?, ?)
                    RETURNING event_id
                    """,
                    (sample_id, json.dumps(event)),
                )
                event_ids.append(cursor.fetchone()[0])

            return event_ids

    def complete_sample(self, id: int | str, epoch: int, summary: JsonData) -> int:
        """Note that a sample has completed processing. Returns the internal summary_id."""
        with self._get_connection() as conn:
            # First get the sample_id
            cursor = conn.execute(
                """
                SELECT sample_id
                FROM samples
                WHERE location = ? AND id = ? AND epoch = ?
            """,
                (self.location, str(id), epoch),
            )

            row = cursor.fetchone()
            if not row:
                raise ValueError(f"No sample found for id={id}, epoch={epoch}")

            sample_id = row[0]

            # Then insert the summary
            cursor = conn.execute(
                """
                INSERT INTO sample_summaries (sample_id, data)
                VALUES (?, ?)
                RETURNING summary_id
            """,
                (sample_id, json.dumps(summary)),
            )

            return cast(int, cursor.fetchone()[0])

    def get_samples(self) -> Iterator[SampleInfo]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT s.id as sample_id, s.epoch as sample_epoch, s.data as sample_data, ss.data as summary_data
                FROM samples s
                LEFT JOIN sample_summaries ss ON s.sample_id = ss.sample_id
                WHERE s.location = ?
                ORDER BY s.sample_id
            """,
                (self.location,),
            )

            for row in cursor:
                id = row["sample_id"]
                epoch = row["sample_epoch"]
                sample = row["sample_data"]
                summary = None
                if row["summary_data"] is not None:
                    summary = json.loads(row["summary_data"])
                yield SampleInfo(
                    id=id,
                    epoch=epoch,
                    sample=EvalSample.model_validate_json(sample),
                    summary=summary,
                )

    def get_events(
        self,
        id: str | None = None,
        epoch: int | None = None,
        after_event_id: int | None = None,
    ) -> Iterator[EventInfo]:
        if id is not None and epoch is None:
            raise ValueError("If id is provided, epoch must also be provided")

        with self._get_connection() as conn:
            query = """
                SELECT s.id, s.epoch, e.data, e.event_id
                FROM events e
                JOIN samples s ON e.sample_id = s.sample_id
                WHERE s.location = ?
            """
            params: list[str | int] = [self.location]

            if id is not None and epoch is not None:
                query += " AND s.id = ? AND s.epoch = ?"
                params.extend([id, epoch])

            if after_event_id is not None:
                query += " AND e.event_id > ?"
                params.append(after_event_id)

            query += " ORDER BY e.event_id"

            cursor = conn.execute(query, params)

            for row in cursor:
                event = json.loads(row["data"])
                yield EventInfo(
                    id=row["event_id"],
                    sample_id=row["id"],
                    epoch=row["epoch"],
                    event=event,
                )

    def cleanup(self) -> None:
        try:
            os.remove(self.db_path)
        except FileNotFoundError:
            pass


# Example usage:
"""
# Create a logger for a specific location
logger = SampleLogger("experiment_123")

# Log a sample
sample = EvalSample(id="sample_1", epoch=1, input="test input", target="test target")
logger.start_sample(sample)

# Log events using the sample's id and epoch
event = Event(type="start", time="2024-02-13")
logger.log_event(id="sample_1", epoch=1, event=event)

# Complete the sample using the sample's id and epoch
summary = SampleSummary(id="sample_1", epoch=1, input="test input", target="test target")
logger.complete_sample(id="sample_1", epoch=1, summary=summary)

# Query all samples
for sample_with_summary in logger.get_samples():
    print(f"Sample: {sample_with_summary.sample}")
    if sample_with_summary.summary:
        print(f"Summary: {sample_with_summary.summary}")

# Query all events
for sample_id, epoch, event in logger.get_events():
    print(f"Event for sample {sample_id} epoch {epoch}: {event}")

# Query events for a specific sample
for sample_id, epoch, event in logger.get_events(id="sample_1", epoch=1):
    print(f"Event for sample {sample_id} epoch {epoch}: {event}")

# Query events for a specific sample after a specific event_id
for sample_id, epoch, event in logger.get_events(id="sample_1", epoch=1, after_event_id=1000):
    print(f"Event for sample {sample_id} epoch {epoch}: {event}")

# Clean up when done
logger.cleanup()
"""
