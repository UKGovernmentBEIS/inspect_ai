import sqlite3
from pathlib import Path

import pytest

from inspect_ai._util.kvstore import KVStore


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Provide a temporary database path for each test."""
    return tmp_path / "test.db"


@pytest.fixture
def store(db_path: Path) -> KVStore:
    """Provide a KVStore instance."""
    return KVStore(str(db_path))


def test_kvstore_basic_put_get(store: KVStore) -> None:
    with store:
        store.put("key1", "value1")
        assert store.get("key1") == "value1"


def test_kvstore_missing_key_returns_none(store: KVStore) -> None:
    with store:
        assert store.get("nonexistent") is None


def test_kvstore_update_existing_key(store: KVStore) -> None:
    with store:
        store.put("key1", "value1")
        store.put("key1", "value2")
        assert store.get("key1") == "value2"


def test_kvstore_delete_existing_key(store: KVStore) -> None:
    with store:
        store.put("key1", "value1")
        assert store.delete("key1") is True
        assert store.get("key1") is None


def test_kvstore_delete_nonexistent_key(store: KVStore) -> None:
    with store:
        assert store.delete("nonexistent") is False


def test_kvstore_affects_count(store: KVStore) -> None:
    with store:
        store.put("key1", "value1")
        store.put("key2", "value2")
        assert store.count() == 2
        store.delete("key1")
        assert store.count() == 1


def test_kvstore_count_empty_store(store: KVStore) -> None:
    with store:
        assert store.count() == 0


def test_kvstore_count_with_entries(store: KVStore) -> None:
    with store:
        store.put("key1", "value1")
        store.put("key2", "value2")
        assert store.count() == 2


def test_kvstore_rotation_with_max_entries(db_path: Path) -> None:
    store = KVStore(str(db_path), max_entries=2)
    with store:
        store.put("key1", "value1")
        store.put("key2", "value2")
        store.put("key3", "value3")

        assert store.count() == 2
        assert store.get("key1") is None  # Oldest entry should be removed
        assert store.get("key2") == "value2"
        assert store.get("key3") == "value3"


def test_kvstore_persistence_between_sessions(db_path: Path) -> None:
    # First session
    with KVStore(str(db_path)) as store:
        store.put("key1", "value1")

    # Second session
    with KVStore(str(db_path)) as store:
        assert store.get("key1") == "value1"


def test_kvstore_context_manager_closes_connection(store: KVStore) -> None:
    with store:
        store.put("key1", "value1")

    # Connection should be closed after context exit
    with pytest.raises(sqlite3.ProgrammingError):
        store.conn.execute("SELECT 1")


def test_kvstore_empty_string_values(store: KVStore) -> None:
    with store:
        store.put("key1", "")
        assert store.get("key1") == ""


def test_kvstore_special_characters_in_keys_and_values(store: KVStore) -> None:
    with store:
        special = "!@#$%^&*()_+-=[]{}|;:'\",.<>?"
        store.put(special, special)
        assert store.get(special) == special


def test_kvstore_very_long_strings(store: KVStore) -> None:
    with store:
        long_string = "x" * 10000
        store.put("long_key", long_string)
        assert store.get("long_key") == long_string


def test_kvstore_multiple_rotations(db_path: Path) -> None:
    store = KVStore(str(db_path), max_entries=3)
    with store:
        for i in range(5):
            store.put(f"key{i}", f"value{i}")

        assert store.count() == 3
        assert store.get("key0") is None
        assert store.get("key1") is None
        assert store.get("key2") == "value2"
        assert store.get("key3") == "value3"
        assert store.get("key4") == "value4"


def test_kvstore_using_store_without_context_manager() -> None:
    with pytest.raises(AttributeError):
        store = KVStore("test.db")
        store.put("key1", "value1")  # Should fail because conn isn't initialized
