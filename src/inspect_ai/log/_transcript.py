import sqlite3
from logging import getLogger

from inspect_ai._util.error import exception_message
from inspect_ai.log._log import TranscriptEvent

logger = getLogger(__name__)


def init_transcript(transcript: str) -> bool:
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(transcript)

        create_table_sql = """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sample_id TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                event_json TEXT NOT NULL
            );
        """
        create_index_sql = """
            CREATE INDEX IF NOT EXISTS idx_sample_id_epoch ON events (sample_id, epoch);
        """

        c = conn.cursor()
        c.execute(create_table_sql)
        c.execute(create_index_sql)

        conn.commit()
        return True
    except sqlite3.Error as ex:
        logger.warn(f"Unable to create transcript database: {exception_message(ex)}")
        return False
    finally:
        if conn is not None:
            conn.close()


def log_transcript_events(transcript: str, events: list[TranscriptEvent]) -> None:
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(transcript)

        sql = """
            INSERT INTO events(sample_id, epoch, timestamp, event_json)
            VALUES(?, ?, ?, ?)
        """

        data = [
            (
                te.sample_id,
                te.epoch,
                te.event.timestamp.isoformat(),
                te.event.model_dump_json(),
            )
            for te in events
        ]

        cur = conn.cursor()
        cur.executemany(sql, data)
        conn.commit()

    except sqlite3.Error as ex:
        logger.warn(f"Error writing to transcript database: {exception_message(ex)}")

    finally:
        if conn is not None:
            conn.close()


def transcript_file(log: str) -> str:
    return log[: -len(".json")] + ".db"
