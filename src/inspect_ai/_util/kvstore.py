import sqlite3
from contextlib import AbstractContextManager
from typing import Any, Optional, cast

from .appdirs import inspect_data_dir


class KVStore(AbstractContextManager["KVStore"]):
    def __init__(self, filename: str, max_entries: int | None = None):
        self.filename = filename
        self.max_entries = max_entries

    def __enter__(self) -> "KVStore":
        self.conn = sqlite3.connect(self.filename)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS kv_store (
                key TEXT PRIMARY KEY,
                value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()
        return self

    def __exit__(self, *excinfo: Any) -> None:
        self.conn.close()

    def put(self, key: str, value: str) -> None:
        # Insert or update the value
        self.conn.execute(
            """
            INSERT OR REPLACE INTO kv_store (key, value, created_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """,
            (key, value),
        )

        # If we have a max_entries limit, remove oldest entries
        if self.max_entries:
            count = self.count()
            if count > self.max_entries:
                self.conn.execute(
                    """
                    DELETE FROM kv_store
                    WHERE key IN (
                        SELECT key FROM kv_store
                        ORDER BY created_at ASC
                        LIMIT ?
                    )
                    """,
                    (max(0, count - self.max_entries),),
                )

        self.conn.commit()

    def get(self, key: str) -> Optional[str]:
        cursor = self.conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,))
        result = cursor.fetchone()
        return result[0] if result else None

    def delete(self, key: str) -> bool:
        cursor = self.conn.execute("DELETE FROM kv_store WHERE key = ?", (key,))
        self.conn.commit()
        return cursor.rowcount > 0

    def count(self) -> int:
        cursor = self.conn.execute("SELECT COUNT(*) FROM kv_store")
        return cast(int, cursor.fetchone()[0])


def inspect_kvstore(name: str, max_entries: int | None = None) -> KVStore:
    filename = inspect_data_dir("kvstore") / f"{name}.db"
    return KVStore(filename.as_posix(), max_entries=max_entries)
