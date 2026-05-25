# Bounded-Memory Checkpointer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move checkpoint cumulative event/pool/attachment state out of `_Checkpointer` Python lists and into a checkpoint-local SQLite store while preserving existing checkpoint snapshot files.

**Architecture:** Add a private `CheckpointEventStore` under `inspect_ai.util._checkpoint` that merges one transcript event/update at a time into SQLite. `_Checkpointer` delegates event accumulation and snapshot file export to this store, retaining only orchestration state for triggers, restic, sidecars, and agent-state callbacks. The existing exported files (`events.json`, `events_data.json`, `attachments.json`, `store.json`, `agent_state.json`) remain the checkpoint artifact for this round.

**Tech Stack:** Python 3.13, SQLite via stdlib `sqlite3`, Pydantic event models, existing `inspect_ai.log._pool` expansion semantics, `pytest`, `ruff`, `mypy`.

---

## File Structure

- Create `src/inspect_ai/util/_checkpoint/event_store.py`
  - Defines `CheckpointEventStore` and `CheckpointEventStoreCounts`.
  - Owns SQLite schema, event merge/update collapse, DB-backed pool lookup, cumulative attachments, and snapshot JSON export.
- Modify `src/inspect_ai/util/_checkpoint/checkpointer_impl.py`
  - Replace `_condensed_events`, `_condensed_event_index`, `_msg_pool`, `_msg_index`, `_call_pool`, `_call_index` with `CheckpointEventStore`.
  - Pass transcript attachments into event-store merge calls.
  - Export host context through event store.
  - Update TEMPORARY diagnostics to report store counts.
- Modify `src/inspect_ai/log/_pool.py`
  - Add small reusable helpers for hashing/condensing one event with callback-based pool lookup, or expose the existing hash/ref primitives needed by `CheckpointEventStore`.
- Modify `src/inspect_ai/log/_transcript.py` only if late provider-backed seeding needs a streaming history method. Prefer not to widen this API unless tests prove it necessary.
- Modify `tests/checkpoint/test_checkpointer.py`
  - Update tests that inspect private `_Checkpointer` cumulative lists.
  - Add bounded-memory/checkpoint-store integration tests.
- Create `tests/checkpoint/test_checkpoint_event_store.py`
  - Store-level unit tests for merge, update collapse, pool stability, attachments, and export round-trip.

---

### Task 1: Add Store Skeleton and Schema

**Files:**
- Create: `src/inspect_ai/util/_checkpoint/event_store.py`
- Create: `tests/checkpoint/test_checkpoint_event_store.py`

- [ ] **Step 1: Write failing schema/counts tests**

Add this test file:

```python
from __future__ import annotations

from pathlib import Path

from inspect_ai.util._checkpoint.event_store import CheckpointEventStore


def test_checkpoint_event_store_initializes_schema(tmp_path: Path) -> None:
    store = CheckpointEventStore(tmp_path / "checkpoint-state.sqlite")

    counts = store.counts()

    assert counts.events == 0
    assert counts.message_pool == 0
    assert counts.call_pool == 0
    assert counts.attachments == 0
    assert (tmp_path / "checkpoint-state.sqlite").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/checkpoint/test_checkpoint_event_store.py::test_checkpoint_event_store_initializes_schema -q
```

Expected: FAIL with `ModuleNotFoundError` or missing `CheckpointEventStore`.

- [ ] **Step 3: Implement store skeleton**

Create `src/inspect_ai/util/_checkpoint/event_store.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection, connect


@dataclass(frozen=True)
class CheckpointEventStoreCounts:
    events: int
    message_pool: int
    call_pool: int
    attachments: int
    db_bytes: int


class CheckpointEventStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._conn = connect(self._path)
        self._conn.row_factory = None
        self._init_schema(self._conn)

    @property
    def path(self) -> Path:
        return self._path

    def counts(self) -> CheckpointEventStoreCounts:
        return CheckpointEventStoreCounts(
            events=self._count_rows("events"),
            message_pool=self._count_rows("message_pool"),
            call_pool=self._count_rows("call_pool"),
            attachments=self._count_rows("attachments"),
            db_bytes=self._path.stat().st_size if self._path.exists() else 0,
        )

    def close(self) -> None:
        self._conn.close()

    def _count_rows(self, table: str) -> int:
        row = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        assert row is not None
        return int(row[0])

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
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/checkpoint/test_checkpoint_event_store.py::test_checkpoint_event_store_initializes_schema -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/inspect_ai/util/_checkpoint/event_store.py tests/checkpoint/test_checkpoint_event_store.py
git commit -m "feat(checkpoint): add SQLite event store skeleton"
```

---

### Task 2: Implement Event Merge and Update Collapse

**Files:**
- Modify: `src/inspect_ai/util/_checkpoint/event_store.py`
- Modify: `tests/checkpoint/test_checkpoint_event_store.py`

- [ ] **Step 1: Add failing tests for order and update collapse**

Append to `tests/checkpoint/test_checkpoint_event_store.py`:

```python
import json

from inspect_ai.event._info import InfoEvent


def _exported_events(work_dir: Path) -> list[dict[str, object]]:
    return json.loads((work_dir / "events.json").read_text())


def test_checkpoint_event_store_exports_events_in_first_seen_order(tmp_path: Path) -> None:
    event_store = CheckpointEventStore(tmp_path / "checkpoint-state.sqlite")
    first = InfoEvent(data="first")
    second = InfoEvent(data="second")

    event_store.merge_event(first, attachments={})
    event_store.merge_event(second, attachments={})
    event_store.export_snapshot_files(tmp_path, store_json={}, agent_state=None)

    events = _exported_events(tmp_path)
    assert [event["data"] for event in events] == ["first", "second"]
    assert [event["uuid"] for event in events] == [first.uuid, second.uuid]


def test_checkpoint_event_store_updates_existing_logical_event(tmp_path: Path) -> None:
    event_store = CheckpointEventStore(tmp_path / "checkpoint-state.sqlite")
    event = InfoEvent(data="first")

    event_store.merge_event(event, attachments={})
    event.data = "updated"
    event_store.merge_event(event, attachments={})
    event_store.export_snapshot_files(tmp_path, store_json={}, agent_state=None)

    events = _exported_events(tmp_path)
    assert len(events) == 1
    assert events[0]["uuid"] == event.uuid
    assert events[0]["data"] == "updated"
    assert event_store.counts().events == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/checkpoint/test_checkpoint_event_store.py -q
```

Expected: FAIL because `merge_event()` and `export_snapshot_files()` are missing.

- [ ] **Step 3: Implement event merge/export without pools**

Update `event_store.py` imports and class:

```python
import json
from collections.abc import Mapping
from typing import Any

from pydantic_core import to_jsonable_python
from shortuuid import uuid

from inspect_ai.event._event import Event
```

Add methods inside `CheckpointEventStore`:

```python
    def merge_event(self, event: Event, attachments: Mapping[str, str]) -> None:
        if event.uuid is None:
            event.uuid = uuid()
        event_json = json.dumps(
            to_jsonable_python(event, exclude_none=True, fallback=lambda _: None),
            separators=(",", ":"),
        )
        with self._conn:
            row = self._conn.execute(
                "SELECT first_seq FROM events WHERE logical_id = ?",
                (event.uuid,),
            ).fetchone()
            if row is None:
                first_seq = self._next_event_seq()
                self._conn.execute(
                    "INSERT INTO events(logical_id, first_seq, latest_json) VALUES (?, ?, ?)",
                    (event.uuid, first_seq, event_json),
                )
            else:
                self._conn.execute(
                    "UPDATE events SET latest_json = ? WHERE logical_id = ?",
                    (event_json, event.uuid),
                )
            for ref in self._attachment_refs(event):
                content = attachments.get(ref)
                if content is not None:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO attachments(hash, content) VALUES (?, ?)",
                        (ref, content),
                    )

    def merge_events(self, events: list[Event], attachments: Mapping[str, str]) -> None:
        for event in events:
            self.merge_event(event, attachments)

    def export_snapshot_files(
        self,
        sample_working_dir: str | Path,
        *,
        store_json: object,
        agent_state: Mapping[str, object] | None,
    ) -> None:
        sample_dir = Path(sample_working_dir)
        self._write_json_array(
            sample_dir / "events.json",
            self._conn.execute("SELECT latest_json FROM events ORDER BY first_seq"),
        )
        (sample_dir / "events_data.json").write_text('{"messages":[],"calls":[]}\n')
        self._write_json_object_from_rows(
            sample_dir / "attachments.json",
            self._conn.execute("SELECT hash, content FROM attachments ORDER BY hash"),
        )
        (sample_dir / "store.json").write_text(json.dumps(store_json) + "\n")
        if agent_state is not None:
            (sample_dir / "agent_state.json").write_text(json.dumps(agent_state) + "\n")

    def _next_event_seq(self) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(first_seq), -1) + 1 FROM events").fetchone()
        assert row is not None
        return int(row[0])

    @staticmethod
    def _attachment_refs(event: Event) -> set[str]:
        refs: set[str] = set()

        def collect(value: object) -> None:
            if isinstance(value, str):
                if value.startswith("attachment://"):
                    refs.add(value.removeprefix("attachment://"))
            elif isinstance(value, dict):
                for item in value.values():
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(event.model_dump(mode="python"))
        return refs

    @staticmethod
    def _write_json_array(path: Path, rows: object) -> None:
        with path.open("w") as file:
            file.write("[")
            first = True
            for (json_text,) in rows:  # type: ignore[assignment]
                if not first:
                    file.write(",")
                file.write(str(json_text))
                first = False
            file.write("]\n")

    @staticmethod
    def _write_json_object_from_rows(path: Path, rows: object) -> None:
        with path.open("w") as file:
            file.write("{")
            first = True
            for key, value in rows:  # type: ignore[assignment]
                if not first:
                    file.write(",")
                file.write(json.dumps(str(key)))
                file.write(":")
                file.write(json.dumps(value))
                first = False
            file.write("}\n")
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/checkpoint/test_checkpoint_event_store.py -q
```

Expected: PASS for current tests.

- [ ] **Step 5: Run type/lint and fix only issues in touched files**

Run:

```bash
uv run ruff check src/inspect_ai/util/_checkpoint/event_store.py tests/checkpoint/test_checkpoint_event_store.py
uv run mypy src/inspect_ai/util/_checkpoint/event_store.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/inspect_ai/util/_checkpoint/event_store.py tests/checkpoint/test_checkpoint_event_store.py
git commit -m "feat(checkpoint): store latest event versions on disk"
```

---

### Task 3: Add DB-Backed Pool Condensing

**Files:**
- Modify: `src/inspect_ai/log/_pool.py`
- Modify: `src/inspect_ai/util/_checkpoint/event_store.py`
- Modify: `tests/checkpoint/test_checkpoint_event_store.py`

- [ ] **Step 1: Add failing pool round-trip test**

Append to `tests/checkpoint/test_checkpoint_event_store.py`:

```python
from inspect_ai.log import expand_events
from inspect_ai.event._model import ModelEvent
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageSystem, ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput


def _model_event(messages: list[object]) -> ModelEvent:
    return ModelEvent(
        model="test",
        input=messages,
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(),
        call=None,
    )


def test_checkpoint_event_store_exports_stable_message_pool(tmp_path: Path) -> None:
    event_store = CheckpointEventStore(tmp_path / "checkpoint-state.sqlite")
    sys = ChatMessageSystem(content="sys")
    user = ChatMessageUser(content="question")
    assistant = ChatMessageAssistant(content="answer")

    event_store.merge_event(_model_event([sys, user]), attachments={})
    event_store.merge_event(_model_event([sys, user, assistant]), attachments={})
    event_store.export_snapshot_files(tmp_path, store_json={}, agent_state=None)

    events_data = json.loads((tmp_path / "events_data.json").read_text())
    events = json.loads((tmp_path / "events.json").read_text())
    assert len(events_data["messages"]) == 3
    assert events[0]["input_refs"] == [[0, 1]]
    assert events[1]["input_refs"] == [[0, 2]]

    expanded = expand_events(
        (tmp_path / "events.json").read_text(),
        (tmp_path / "events_data.json").read_text(),
    )
    model_events = [event for event in expanded if isinstance(event, ModelEvent)]
    assert [len(event.input) for event in model_events] == [2, 3]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/checkpoint/test_checkpoint_event_store.py::test_checkpoint_event_store_exports_stable_message_pool -q
```

Expected: FAIL because `events_data.messages` is empty and events are uncondensed.

- [ ] **Step 3: Expose callback-based condense helpers**

In `src/inspect_ai/log/_pool.py`, add imports if needed:

```python
from collections.abc import Callable
```

Add helper functions near existing condense functions:

```python
def condense_model_event_inputs_with_lookup(
    event: Event,
    lookup_message: Callable[[ChatMessage], int],
) -> Event:
    if isinstance(event, ModelEvent) and event.input:
        raw_indices = [lookup_message(message) for message in event.input]
        return event.model_copy(
            update={
                "input": [],
                "input_refs": _compress_refs(raw_indices),
            }
        )
    return event


def condense_model_event_calls_with_lookup(
    event: Event,
    lookup_call: Callable[[JsonValue], int],
) -> Event:
    if isinstance(event, ModelEvent) and event.call and event.call.request:
        msg_key = "messages" if "messages" in event.call.request else "contents"
        msgs = event.call.request.get(msg_key)
        if isinstance(msgs, list):
            raw_indices = [lookup_call(msg) for msg in msgs]
            new_request = {k: v for k, v in event.call.request.items() if k != msg_key}
            new_call = event.call.model_copy(
                update={
                    "request": new_request,
                    "call_refs": _compress_refs(raw_indices),
                    "call_key": msg_key,
                }
            )
            return event.model_copy(update={"call": new_call})
    return event
```

Use the existing private `_compress_refs()` and existing `ChatMessage`, `JsonValue`, `Event`, `ModelEvent` imports already in `_pool.py`.

- [ ] **Step 4: Wire message pool lookup in event store**

Update `event_store.py` imports:

```python
from pydantic_core import to_jsonable_python
from inspect_ai._util.hash import mm3_hash
from inspect_ai.log._pool import condense_model_event_inputs_with_lookup, condense_model_event_calls_with_lookup
from inspect_ai.model._chat_message import ChatMessage
from pydantic import JsonValue
```

Add methods:

```python
    def _condense_event(self, event: Event) -> Event:
        event = condense_model_event_inputs_with_lookup(event, self._message_pos)
        event = condense_model_event_calls_with_lookup(event, self._call_pos)
        return event

    def _message_pos(self, message: ChatMessage) -> int:
        message_jsonable = to_jsonable_python(message, exclude_none=True, fallback=lambda _: None)
        message_json = json.dumps(message_jsonable, sort_keys=True)
        return self._pool_pos("message_pool", mm3_hash(message_json), message_json)

    def _call_pos(self, call_message: JsonValue) -> int:
        call_json = json.dumps(call_message, sort_keys=True)
        return self._pool_pos("call_pool", mm3_hash(call_json), call_json)

    def _pool_pos(self, table: str, hash_value: str, json_text: str) -> int:
        row = self._conn.execute(f"SELECT pos FROM {table} WHERE hash = ?", (hash_value,)).fetchone()
        if row is not None:
            return int(row[0])
        pos_row = self._conn.execute(f"SELECT COALESCE(MAX(pos), -1) + 1 FROM {table}").fetchone()
        assert pos_row is not None
        pos = int(pos_row[0])
        self._conn.execute(
            f"INSERT INTO {table}(pos, hash, json) VALUES (?, ?, ?)",
            (pos, hash_value, json_text),
        )
        return pos
```

In `merge_event()`, before serializing:

```python
        event = self._condense_event(event)
```

Update `export_snapshot_files()` to write real events data:

```python
        self._write_events_data(sample_dir / "events_data.json")
```

Add:

```python
    def _write_events_data(self, path: Path) -> None:
        with path.open("w") as file:
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

    @staticmethod
    def _write_json_array_to_file(file: object, rows: object) -> None:
        file.write("[")
        first = True
        for (json_text,) in rows:  # type: ignore[assignment]
            if not first:
                file.write(",")
            file.write(str(json_text))
            first = False
        file.write("]")
```

Then make `_write_json_array()` delegate to `_write_json_array_to_file()`.

- [ ] **Step 5: Run pool test**

Run:

```bash
uv run pytest tests/checkpoint/test_checkpoint_event_store.py::test_checkpoint_event_store_exports_stable_message_pool -q
```

Expected: PASS.

- [ ] **Step 6: Add and pass call pool test**

Append a second test:

```python
from inspect_ai.model._model_call import ModelCall


def test_checkpoint_event_store_exports_stable_call_pool(tmp_path: Path) -> None:
    event_store = CheckpointEventStore(tmp_path / "checkpoint-state.sqlite")
    event = _model_event([ChatMessageUser(content="visible")])
    event.call = ModelCall.create(
        request={"messages": [{"role": "user", "content": "hidden"}]},
        response={"ok": True},
    )

    event_store.merge_event(event, attachments={})
    event_store.export_snapshot_files(tmp_path, store_json={}, agent_state=None)

    events_data = json.loads((tmp_path / "events_data.json").read_text())
    events = json.loads((tmp_path / "events.json").read_text())
    assert events_data["calls"] == [{"role": "user", "content": "hidden"}]
    assert events[0]["call"]["call_refs"] == [[0, 0]]
    assert "messages" not in events[0]["call"]["request"]
```

Run:

```bash
uv run pytest tests/checkpoint/test_checkpoint_event_store.py::test_checkpoint_event_store_exports_stable_call_pool -q
```

Expected: PASS.

- [ ] **Step 7: Run full store tests and type/lint**

Run:

```bash
uv run pytest tests/checkpoint/test_checkpoint_event_store.py -q
uv run ruff check src/inspect_ai/log/_pool.py src/inspect_ai/util/_checkpoint/event_store.py tests/checkpoint/test_checkpoint_event_store.py
uv run mypy src/inspect_ai/log/_pool.py src/inspect_ai/util/_checkpoint/event_store.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/inspect_ai/log/_pool.py src/inspect_ai/util/_checkpoint/event_store.py tests/checkpoint/test_checkpoint_event_store.py
git commit -m "feat(checkpoint): condense event pools on disk"
```

---

### Task 4: Export Attachments and Host Context Files

**Files:**
- Modify: `src/inspect_ai/util/_checkpoint/event_store.py`
- Modify: `tests/checkpoint/test_checkpoint_event_store.py`

- [ ] **Step 1: Add failing attachment and host-context tests**

Append:

```python
from inspect_ai.event._model import ModelEvent


def test_checkpoint_event_store_retains_cumulative_attachments(tmp_path: Path) -> None:
    event_store = CheckpointEventStore(tmp_path / "checkpoint-state.sqlite")
    event = InfoEvent(data={"blob": "attachment://abc"})

    event_store.merge_event(event, attachments={"abc": "payload"})
    event_store.export_snapshot_files(tmp_path, store_json={}, agent_state=None)

    assert json.loads((tmp_path / "attachments.json").read_text()) == {"abc": "payload"}

    event_store.merge_event(InfoEvent(data="later"), attachments={})
    event_store.export_snapshot_files(tmp_path, store_json={}, agent_state=None)

    assert json.loads((tmp_path / "attachments.json").read_text()) == {"abc": "payload"}


def test_checkpoint_event_store_writes_store_and_agent_state(tmp_path: Path) -> None:
    event_store = CheckpointEventStore(tmp_path / "checkpoint-state.sqlite")
    event_store.export_snapshot_files(
        tmp_path,
        store_json={"x": 1},
        agent_state={"agent": {"step": 2}},
    )

    assert json.loads((tmp_path / "store.json").read_text()) == {"x": 1}
    assert json.loads((tmp_path / "agent_state.json").read_text()) == {
        "agent": {"step": 2}
    }
```

- [ ] **Step 2: Run tests**

Run:

```bash
uv run pytest tests/checkpoint/test_checkpoint_event_store.py::test_checkpoint_event_store_retains_cumulative_attachments tests/checkpoint/test_checkpoint_event_store.py::test_checkpoint_event_store_writes_store_and_agent_state -q
```

Expected: attachment test may already pass; host context should pass if Task 2 implemented it. If both pass, continue; these tests lock behavior.

- [ ] **Step 3: If needed, fix attachment scanning/export**

Ensure `_attachment_refs()` scans condensed events and nested dict/list structures. Keep cumulative rows with `INSERT OR IGNORE`.

- [ ] **Step 4: Run store tests**

Run:

```bash
uv run pytest tests/checkpoint/test_checkpoint_event_store.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/inspect_ai/util/_checkpoint/event_store.py tests/checkpoint/test_checkpoint_event_store.py
git commit -m "feat(checkpoint): retain checkpoint attachments on disk"
```

---

### Task 5: Wire `_Checkpointer` to `CheckpointEventStore`

**Files:**
- Modify: `src/inspect_ai/util/_checkpoint/checkpointer_impl.py`
- Modify: `tests/checkpoint/test_checkpointer.py`

- [ ] **Step 1: Update tests to assert store-backed state**

In `tests/checkpoint/test_checkpointer.py`, add a test near existing checkpoint stream tests:

```python
async def test_checkpointer_uses_store_instead_of_cumulative_python_lists(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    cp = _Checkpointer(
        config=CheckpointConfig(trigger=TurnInterval(every=1)),
        sample_checkpoints_dir=str(tmp_path / "ckpts"),
        sample_working_dir=str(work),
        host_restic=Path("/fake"),
        restic_password="pwd",
    )

    assert not hasattr(cp, "_condensed_events")
    assert not hasattr(cp, "_msg_pool")
    assert not hasattr(cp, "_call_pool")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/checkpoint/test_checkpointer.py::test_checkpointer_uses_store_instead_of_cumulative_python_lists -q
```

Expected: FAIL because `_Checkpointer` still has cumulative lists.

- [ ] **Step 3: Replace cumulative fields with event store**

In `checkpointer_impl.py`:

- Remove imports of `EventsData`, `condense_model_event_calls`, `condense_model_event_inputs`, `ChatMessage`, and `JsonValue` if no longer used.
- Import:

```python
from pydantic_core import to_jsonable_python
from .event_store import CheckpointEventStore
```

In `_Checkpointer.__init__`, replace the cumulative fields with:

```python
        self._event_store = CheckpointEventStore(
            Path(self._sample_working_dir) / "checkpoint-state.sqlite"
        )
```

Remove `_merge_events_into_checkpoint_stream()` and `_merge_event_into_checkpoint_stream()` or leave as thin wrappers temporarily:

```python
    def _merge_events_into_checkpoint_stream(
        self, events: Sequence[Event], attachments: Mapping[str, str] | None = None
    ) -> None:
        self._event_store.merge_events(events, attachments or {})
```

Update `_track_transcript_event()`:

```python
    def _track_transcript_event(self, event: Event) -> None:
        self._event_store.merge_event(event, transcript().attachments)
        self._events_since_diagnostic += 1
        if self._events_since_diagnostic >= _TEMPORARY_CHECKPOINT_DIAGNOSTIC_INTERVAL:
            self._events_since_diagnostic = 0
            self._log_temporary_diagnostics("event")
```

Update seeding:

```python
            seed_events = list(ts.events)
            self._event_store.merge_events(seed_events, ts.attachments)
```

Update `_write_host_context()`:

```python
        if events:
            self._event_store.merge_events(events, attachments)
        agent_state = None
        if self._on_checkpoint_callbacks:
            agent_state = {key: cb() for key, cb in self._on_checkpoint_callbacks.items()}
        self._event_store.export_snapshot_files(
            sample_working_dir,
            store_json=store_jsonable(store),
            agent_state=agent_state,
        )
```

- [ ] **Step 4: Update diagnostics to use counts**

Replace `_log_temporary_diagnostics()` body with:

```python
        extra = extra or {}
        counts = self._event_store.counts()
        logger.info(
            "TEMPORARY checkpoint: source=%s events=%s message_pool=%s call_pool=%s attachments=%s db_bytes=%s callbacks=%s next_checkpoint_id=%s turns_since_fire=%s extra=%s",
            source,
            counts.events,
            counts.message_pool,
            counts.call_pool,
            counts.attachments,
            counts.db_bytes,
            len(self._on_checkpoint_callbacks),
            self._next_checkpoint_id,
            self._turns_since_fire,
            dict(extra),
        )
```

- [ ] **Step 5: Run focused checkpointer tests**

Run:

```bash
uv run pytest tests/checkpoint/test_checkpointer.py::test_checkpointer_uses_store_instead_of_cumulative_python_lists tests/checkpoint/test_checkpointer.py::test_write_host_context_accumulates_across_fires tests/checkpoint/test_checkpointer.py::test_fire_collapses_same_cycle_event_updates -q
```

Expected: PASS.

- [ ] **Step 6: Run all checkpoint tests**

Run:

```bash
uv run pytest tests/checkpoint/test_checkpointer.py tests/checkpoint/test_checkpoint_event_store.py -q
```

Expected: PASS for asyncio tests; trio variants may skip as usual.

- [ ] **Step 7: Type/lint**

Run:

```bash
uv run ruff check src/inspect_ai/util/_checkpoint/checkpointer_impl.py src/inspect_ai/util/_checkpoint/event_store.py tests/checkpoint/test_checkpointer.py
uv run mypy src/inspect_ai/util/_checkpoint/checkpointer_impl.py src/inspect_ai/util/_checkpoint/event_store.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/inspect_ai/util/_checkpoint/checkpointer_impl.py src/inspect_ai/util/_checkpoint/event_store.py tests/checkpoint/test_checkpointer.py
git commit -m "feat(checkpoint): back checkpoint stream with SQLite"
```

---

### Task 6: Add Bounded Transcript Attachment Regression

**Files:**
- Modify: `tests/checkpoint/test_checkpointer.py`

- [ ] **Step 1: Add failing regression test**

Append near bounded transcript/checkpoint tests:

```python
async def test_checkpoint_retains_attachment_after_transcript_eviction(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    transcript = Transcript(bounded=True, resident_tail=1)
    cp = _Checkpointer(
        config=CheckpointConfig(trigger=TurnInterval(every=1)),
        sample_checkpoints_dir=str(tmp_path / "ckpts"),
        sample_working_dir=str(work),
        host_restic=Path("/fake"),
        restic_password="pwd",
    )

    first = InfoEvent(data={"blob": "attachment://abc"})
    transcript.attachments["abc"] = "payload"

    with patch(
        "inspect_ai.util._checkpoint.checkpointer_impl.transcript",
        return_value=transcript,
    ):
        cp._ensure_transcript_subscription()
        transcript._event(first)
        transcript._event(InfoEvent(data="evict first"))
        await cp._write_host_context(str(work), [], transcript.attachments, Store())

    assert first not in transcript.resident_events
    assert json.loads((work / "attachments.json").read_text()) == {"abc": "payload"}
```

- [ ] **Step 2: Run test**

Run:

```bash
uv run pytest tests/checkpoint/test_checkpointer.py::test_checkpoint_retains_attachment_after_transcript_eviction -q
```

Expected: PASS if Task 5 copied attachments during merge. If it fails, update `_track_transcript_event()` to pass `transcript().attachments` before eviction can prune content, or update transcript notification ordering only if necessary and covered by tests.

- [ ] **Step 3: Run related tests**

Run:

```bash
uv run pytest tests/checkpoint/test_checkpointer.py tests/log/test_transcript_bounded.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/checkpoint/test_checkpointer.py src/inspect_ai/util/_checkpoint/checkpointer_impl.py src/inspect_ai/util/_checkpoint/event_store.py
git commit -m "test(checkpoint): retain attachments after transcript eviction"
```

---

### Task 7: Fix Late Provider-Backed Seeding Without Full List Materialization

**Files:**
- Modify: `src/inspect_ai/log/_transcript.py`
- Modify: `src/inspect_ai/log/_recorders/buffer/history_provider.py`
- Modify: `src/inspect_ai/util/_checkpoint/checkpointer_impl.py`
- Modify: `tests/checkpoint/test_checkpointer.py`
- Modify: `tests/test_helpers/transcript.py`

- [ ] **Step 1: Add provider streaming protocol method**

In `TranscriptHistoryProvider` in `src/inspect_ai/log/_transcript.py`, add:

```python
    def iter_events(self) -> Iterator[Event]: ...
```

In `_TranscriptEventsView.__iter__()`, keep existing behavior or call `provider.iter_events()` if implemented. In `BufferTranscriptHistoryProvider`, implement:

```python
    def iter_events(self) -> Iterator[Event]:
        with self._buffer_db.open_sample_history(self._sample_id, self._epoch) as history:
            yield from materialize_events_from_history(history)
```

If no existing `materialize_events_from_history()` exists, use the same helper/path as `events()` but yield incrementally. Do not return a list.

- [ ] **Step 2: Update fake providers**

In `tests/test_helpers/transcript.py`, add `iter_events()` to `FakeTranscriptHistoryProvider`:

```python
    def iter_events(self) -> Iterator[Event]:
        return iter(self._events)
```

- [ ] **Step 3: Add failing no-materialize seed test**

In `tests/checkpoint/test_checkpointer.py`, add:

```python
class _SeedOnlyProvider(FakeTranscriptHistoryProvider):
    def events(self) -> list[Event]:
        raise AssertionError("checkpoint seed must not materialize provider.events()")

    def iter_events(self) -> Iterator[Event]:
        return iter(self._events)


async def test_late_checkpointer_provider_seed_does_not_materialize_events(tmp_path: Path) -> None:
    full_history: list[Event] = [InfoEvent(data="evicted"), InfoEvent(data="resident")]
    transcript = Transcript(
        bounded=True,
        resident_tail=1,
        history_provider=_SeedOnlyProvider(full_history),
    )
    for event in full_history:
        transcript._event(event)

    cp = _Checkpointer(
        config=CheckpointConfig(trigger=TurnInterval(every=1)),
        sample_checkpoints_dir=str(tmp_path / "ckpts"),
        sample_working_dir=str(tmp_path / "work"),
        host_restic=Path("/fake"),
        restic_password="pwd",
    )

    with patch(
        "inspect_ai.util._checkpoint.checkpointer_impl.transcript",
        return_value=transcript,
    ):
        cp._ensure_transcript_subscription()
        await cp._write_host_context(str(tmp_path / "work"), [], transcript.attachments, Store())

    events = json.loads((tmp_path / "work" / "events.json").read_text())
    assert [event["data"] for event in events] == ["evicted", "resident"]
```

- [ ] **Step 4: Update checkpointer seeding**

In `_ensure_transcript_subscription()`:

```python
            if ts.resident_events_truncated and ts.full_history_available:
                seed_events_iter = ts._history_provider.iter_events()
            else:
                seed_events_iter = iter(ts.events)
            seed_count = 0
            for event in seed_events_iter:
                self._event_store.merge_event(event, ts.attachments)
                seed_count += 1
```

Avoid `list(...)` in this path. Preserve existing RuntimeError for truncated/no-provider transcripts.

- [ ] **Step 5: Run tests**

Run:

```bash
uv run pytest tests/checkpoint/test_checkpointer.py::test_late_checkpointer_provider_seed_does_not_materialize_events tests/checkpoint/test_checkpointer.py::test_late_checkpointer_subscription_seeds_provider_backed_history -q
```

Expected: PASS.

- [ ] **Step 6: Run type/lint**

Run:

```bash
uv run ruff check src/inspect_ai/log/_transcript.py src/inspect_ai/log/_recorders/buffer/history_provider.py src/inspect_ai/util/_checkpoint/checkpointer_impl.py tests/checkpoint/test_checkpointer.py tests/test_helpers/transcript.py
uv run mypy src/inspect_ai/log/_transcript.py src/inspect_ai/log/_recorders/buffer/history_provider.py src/inspect_ai/util/_checkpoint/checkpointer_impl.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/inspect_ai/log/_transcript.py src/inspect_ai/log/_recorders/buffer/history_provider.py src/inspect_ai/util/_checkpoint/checkpointer_impl.py tests/checkpoint/test_checkpointer.py tests/test_helpers/transcript.py
git commit -m "feat(checkpoint): stream provider-backed checkpoint seed"
```

---

### Task 8: Final Validation and Squash

**Files:**
- Review all touched files.

- [ ] **Step 1: Run focused test suite**

Run:

```bash
uv run pytest tests/checkpoint/test_checkpoint_event_store.py tests/checkpoint/test_checkpointer.py tests/log/test_transcript_bounded.py tests/log/test_sample_history.py tests/log/test_streaming_completion.py tests/_eval/test_retry_error_events.py tests/display/test_textual_transcript.py -q
```

Expected: PASS, with known trio skips if not running trio.

- [ ] **Step 2: Run type/lint for touched code**

Run:

```bash
uv run ruff check src/inspect_ai/util/_checkpoint/event_store.py src/inspect_ai/util/_checkpoint/checkpointer_impl.py src/inspect_ai/log/_pool.py src/inspect_ai/log/_transcript.py src/inspect_ai/log/_recorders/buffer/history_provider.py tests/checkpoint/test_checkpoint_event_store.py tests/checkpoint/test_checkpointer.py
uv run mypy src/inspect_ai/util/_checkpoint/event_store.py src/inspect_ai/util/_checkpoint/checkpointer_impl.py src/inspect_ai/log/_pool.py src/inspect_ai/log/_transcript.py src/inspect_ai/log/_recorders/buffer/history_provider.py
```

Expected: PASS.

- [ ] **Step 3: Inspect for accidental cumulative fields**

Run:

```bash
rg -n "_condensed_events|_condensed_event_index|_msg_pool|_msg_index|_call_pool|_call_index" src/inspect_ai/util/_checkpoint tests/checkpoint
```

Expected: no `_Checkpointer` cumulative list ownership remains. It is acceptable if tests mention the old names only in negative assertions.

- [ ] **Step 4: Inspect for full materialization in checkpoint seed**

Run:

```bash
rg -n "list\(ts\.events\)|list\(transcript\(\)\.events\)|seed_events = list" src/inspect_ai/util/_checkpoint src/inspect_ai/log
```

Expected: no checkpoint seed path materializes full transcript history.

- [ ] **Step 5: Squash implementation commits if requested**

If this work should remain one feature commit on top of the current event-store branch, run an interactive rebase over the checkpoint implementation commits only. Do not squash the existing event-store feature commit unless the user explicitly asks.

- [ ] **Step 6: Push branch**

```bash
git push --force-with-lease metr event-store-transcript
```

Expected: branch updates on `metr/event-store-transcript`.
