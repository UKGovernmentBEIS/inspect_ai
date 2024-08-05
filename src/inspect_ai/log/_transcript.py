import sqlite3
from logging import getLogger
from typing import Callable

import mmh3

from inspect_ai._util.content import Content, ContentImage, ContentText
from inspect_ai._util.error import exception_message
from inspect_ai.log._log import TranscriptEvent
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.solver._subtask.transcript import ModelEvent

logger = getLogger(__name__)


def init_transcript(transcript: str) -> bool:
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(transcript)

        create_events_sql = """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sample_id TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                event_json TEXT NOT NULL
            );
        """
        create_events_index_sql = """
            CREATE INDEX IF NOT EXISTS idx_sample_id_epoch ON events (sample_id, epoch);
        """
        create_content_sql = """
            CREATE TABLE content (
                hash CHAR(32) PRIMARY KEY,
                content TEXT
            );
        """

        c = conn.cursor()
        c.execute(create_events_sql)
        c.execute(create_events_index_sql)
        c.execute(create_content_sql)

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

        # get events w/ content placeholders
        events, content = to_db_transcript_events(events)

        events_sql = """
            INSERT INTO events(sample_id, epoch, timestamp, event_json)
            VALUES(?, ?, ?, ?)
        """

        events_data = [
            (
                te.sample_id,
                te.epoch,
                te.event.timestamp.isoformat(),
                te.event.model_dump_json(),
            )
            for te in events
        ]

        contents_sql = """
            INSERT OR IGNORE INTO content (hash, content)
                VALUES (?, ?);
        """

        cur = conn.cursor()
        cur.executemany(events_sql, events_data)
        if content:
            cur.executemany(contents_sql, list(content.items()))
        conn.commit()

    except sqlite3.Error as ex:
        logger.warn(f"Error writing to transcript database: {exception_message(ex)}")

    finally:
        if conn is not None:
            conn.close()


def transcript_file(log: str) -> str:
    return log[: -len(".json")] + ".db"


CONTENT_PROTOCOL = "dbc://"


def to_db_transcript_events(
    events: list[TranscriptEvent],
) -> tuple[list[TranscriptEvent], dict[str, str]]:
    content: dict[str, str] = {}

    def content_fn(text: str) -> str:
        hash = mm3_hash(text)
        content[hash] = text
        return f"{CONTENT_PROTOCOL}{hash}"

    events = walk_events(events, content_fn)

    return events, content


def walk_events(
    events: list[TranscriptEvent], content_fn: Callable[[str], str]
) -> list[TranscriptEvent]:
    return [walk_event(event, content_fn) for event in events]


def walk_event(
    event: TranscriptEvent, content_fn: Callable[[str], str]
) -> TranscriptEvent:
    if isinstance(event.event, ModelEvent):
        return event.model_copy(
            update=dict(event=walk_model_event(event.event, content_fn))
        )
    else:
        return event


def walk_model_event(event: ModelEvent, content_fn: Callable[[str], str]) -> ModelEvent:
    return event.model_copy(
        update=dict(
            input=[walk_chat_message(message, content_fn) for message in event.input],
        ),
    )


def walk_chat_message(
    message: ChatMessage, content_fn: Callable[[str], str]
) -> ChatMessage:
    if isinstance(message.content, str):
        return message.model_copy(update=dict(content=content_fn(message.content)))
    else:
        return message.model_copy(
            update=dict(
                content=[
                    walk_content(content, content_fn) for content in message.content
                ]
            )
        )


def walk_content(content: Content, content_fn: Callable[[str], str]) -> Content:
    if isinstance(content, ContentText):
        return content.model_copy(update=dict(text=content_fn(content.text)))
    elif isinstance(content, ContentImage):
        return content.model_copy(update=dict(image=content_fn(content.image)))


def mm3_hash(message: str) -> str:
    # Generate the 128-bit hash as two 64-bit integers
    h1, h2 = mmh3.hash64(message.encode("utf-8"))

    # Convert to unsigned integers and then to hexadecimal
    return f"{h1 & 0xFFFFFFFFFFFFFFFF:016x}{h2 & 0xFFFFFFFFFFFFFFFF:016x}"
