# Bounded-Memory Checkpointer Design

## Context

The bounded transcript work limits resident `Transcript` memory by evicting old events and reading full history from a provider when needed. Checkpointing currently defeats that goal when enabled: `_Checkpointer` subscribes to transcript events, condenses each event, and keeps the cumulative checkpoint stream in Python lists and dictionaries for the lifetime of the sample.

The hard requirement for this update is bounded Python memory with checkpointing enabled. Bounded checkpoint duration, bounded disk use, and avoiding cumulative checkpoint rewrites are not hard requirements for this round.

Checkpointing is not live yet, so the on-disk format can change if it substantially simplifies the design. The preferred design below keeps the existing snapshot files initially because it satisfies the memory goal while preserving the current resume/checkpoint compatibility story.

## Goals

- Keep checkpointer Python memory bounded by current event/update size plus small export buffers.
- Preserve checkpoint semantics: stable event order, latest-update collapse by logical event id, stable positional event pools, and self-contained attachment snapshots.
- Keep `_Checkpointer` focused on policy, sidecars, restic backup, and `Checkpointer.track()` callbacks.
- Avoid depending on the log buffer DB for correctness; checkpointing should work with or without bounded transcript logging.
- Keep existing host snapshot files unless a later implementation step proves a DB artifact is simpler.

## Non-Goals

- Bounded checkpoint export time. Exporting cumulative `events.json` can remain O(total history).
- Bounded checkpoint artifact size. Cumulative snapshot files can keep growing.
- A public checkpoint store API.
- A general replacement for the eval log buffer DB.

## Current Problem

`src/inspect_ai/util/_checkpoint/checkpointer_impl.py` currently stores cumulative state in memory:

- `_condensed_events: list[Event]`
- `_condensed_event_index: dict[str | int, int]`
- `_msg_pool: list[ChatMessage]`
- `_msg_index: dict[str, int]`
- `_call_pool: list[JsonValue]`
- `_call_index: dict[str, int]`

These structures grow with total event history. Bounded transcript eviction does not help because the checkpointer has already copied the cumulative condensed stream into its own Python objects.

The current late-seed path also does `list(ts.events)`. With a provider-backed bounded transcript this can materialize full history in memory.

A separate correctness issue exists under bounded transcripts: `_write_host_context()` writes cumulative checkpoint events but receives attachments from `ts.attachments`. Bounded transcript may prune attachments for evicted events, so checkpoint snapshots must retain cumulative attachments independently.

## Chosen Approach

Add a checkpoint-local SQLite store in the sample working directory. `_Checkpointer` writes event deltas into this store as transcript notifications arrive. On checkpoint fire, the store exports the existing snapshot files into the sample working directory, then restic backs up the directory as today.

This gives bounded runtime memory without tying checkpointing to buffer logging internals.

## Components

### `_Checkpointer`

`_Checkpointer` remains the orchestration layer. It should own:

- checkpoint trigger policy;
- restic repo setup and backup calls;
- sidecar writes;
- `Checkpointer.track()` callback registration;
- subscription lifecycle.

It should no longer own cumulative event or pool state. Replace the cumulative lists/dicts with a private `CheckpointEventStore` instance.

### `CheckpointEventStore`

A new private class, likely in `src/inspect_ai/util/_checkpoint/event_store.py`, owns durable checkpoint transcript state for one sample attempt.

Core methods:

- `merge_event(event: Event) -> None`
- `merge_events(events: Iterable[Event]) -> None`
- `export_snapshot_files(sample_working_dir: str, store: Store, agent_state: Mapping[str, JsonValue] | None) -> None`
- `counts() -> CheckpointEventStoreCounts` for TEMPORARY diagnostics and tests
- `close() -> None` if needed

The store is private to checkpointing and can be synchronous. `_Checkpointer` can call it from synchronous transcript callbacks because each merge is one event/update.

## Store Schema

Use a small SQLite DB under the sample working dir, e.g. `checkpoint-state.sqlite`.

### `events`

One row per logical event.

- `logical_id TEXT PRIMARY KEY`
- `first_seq INTEGER NOT NULL UNIQUE`
- `latest_json TEXT NOT NULL`

`logical_id` should be `event.uuid` when present. If an event lacks a uuid, assign one before storage, matching `Transcript._event_key()` behavior. `first_seq` preserves first-seen event order. Later updates overwrite `latest_json` for the same logical id without changing `first_seq`.

### `message_pool`

Stable positional pool for `ModelEvent.input_refs`.

- `pos INTEGER PRIMARY KEY`
- `hash TEXT NOT NULL UNIQUE`
- `json TEXT NOT NULL`

`pos` is zero-based and never changes. Hash input must match the current `condense_model_event_inputs()` semantics so existing event expansion behavior remains equivalent.

### `call_pool`

Stable positional pool for `ModelEvent.call.call_refs`.

- `pos INTEGER PRIMARY KEY`
- `hash TEXT NOT NULL UNIQUE`
- `json TEXT NOT NULL`

`pos` is zero-based and never changes. Hash input must match current `condense_model_event_calls()` semantics.

### `attachments`

Cumulative attachment content needed by checkpointed events.

- `hash TEXT PRIMARY KEY`
- `content TEXT NOT NULL`

Start with cumulative retention. Do not refcount or prune in the first version; checkpoint snapshots are cumulative, and correctness matters more than disk minimization.

### `metadata`

Small store metadata.

- `key TEXT PRIMARY KEY`
- `value TEXT NOT NULL`

Use this for schema version and next sequence if needed. Alternatively compute next sequence from `MAX(first_seq) + 1` inside a transaction.

## Event Condensing

Do not reuse `condense_model_event_inputs()` and `condense_model_event_calls()` directly if doing so requires full in-memory hash indexes. Instead add lower-level helpers or a small adapter that performs lookup-or-insert through the checkpoint store.

The desired shape is:

- walk one event;
- for each model input message, compute the same hash as today;
- look up or insert the message in `message_pool` and return its stable `pos`;
- replace `ModelEvent.input` with compressed `input_refs`;
- for each call request message, compute the same hash as today;
- look up or insert the call entry in `call_pool` and return its stable `pos`;
- replace `ModelEvent.call.request[messages]` with compressed `call_refs`/`call_key`;
- store the condensed event JSON in `events.latest_json`.

The existing list/dict condense helpers can remain for eval logging. Checkpointing needs DB-backed pool lookup to avoid growing Python indexes.

## Attachment Handling

Checkpoint attachments must be independent of `Transcript.attachments`.

When `merge_event()` sees an event, it should collect `attachment://<hash>` refs from the event after transcript processing has rewritten heavy payloads into attachment refs. For each newly referenced hash, copy the content from the current transcript attachment map into the checkpoint attachment table during the same merge. This is safe only while the attachment is still resident in the transcript.

If an event arrives from a late provider-backed seed, attachment content must come from the provider/import source rather than `ts.attachments`, because the bounded transcript may already have pruned old attachments. The store must not rely on `ts.attachments` at checkpoint fire for cumulative correctness.

Export writes all rows in `attachments` to `attachments.json`.

## Snapshot Export

On checkpoint fire:

1. `_Checkpointer` calls `_ensure_transcript_subscription()`.
2. `_write_host_context()` merges any explicit `events` argument into the store.
3. The store exports snapshot files into the sample working dir.
4. `_Checkpointer` writes `store.json` and optional `agent_state.json`, or delegates those writes to the store export method.
5. `_Checkpointer` releases any SQLite transaction before running restic backup.
6. Restic backup and sidecar write proceed as today.

Export should avoid building cumulative Python lists. It should stream rows ordered by `first_seq` / `pos` into JSON files. It is acceptable for export to be O(total history) in time and output bytes.

The first implementation can use simple manual JSON writing:

- write `[`;
- iterate rows;
- write comma-separated JSON object strings;
- write `]` or object wrappers as needed.

`events_data.json` should preserve the existing shape: `{"messages": [...], "calls": [...]}` with positional arrays.

## Late Subscription and Seeding

The normal path should subscribe before meaningful transcript eviction starts. Late subscription still needs defined behavior.

- If the transcript is untruncated, seed from the in-memory events sequence.
- If the transcript is truncated and has no full-history provider, keep raising a clear `RuntimeError`.
- If the transcript is truncated and provider-backed, do not call `list(ts.events)`. Add a streaming provider path or a checkpoint-specific import path that feeds events to `CheckpointEventStore.merge_event()` incrementally.

For the first implementation, it is acceptable to make provider-backed late seed a focused method rather than a broad public API. The key requirement is that it must not materialize full history in one Python list.

## Concurrency and Transactions

Transcript subscription callbacks are synchronous. Each `merge_event()` should use a short transaction and commit quickly.

Snapshot export should use a read transaction or a clear high-water mark so `events.json`, `events_data.json`, and `attachments.json` are mutually consistent. The transaction must not remain open across restic backup or other awaits.

Restic should only see complete snapshot files. Preserve the current sidecar-as-commit-point behavior: write host context, run backups, then write the sidecar.

## Diagnostics

Keep TEMPORARY checkpoint diagnostics during the memory investigation, but change them to report store counts instead of Python list sizes:

- event rows;
- message pool rows;
- call pool rows;
- attachment rows;
- optional DB file size;
- merge count since last diagnostic;
- export duration and row counts.

The diagnostic line should remain scalar-only and include `TEMPORARY` for easy removal.

## Testing

### Store Unit Tests

- New events export in first-seen order.
- Repeated uuid updates overwrite the exported event and do not duplicate it.
- Events without uuid get stable assigned ids.
- Message pool positions are stable across repeated merges and updates.
- Call pool positions are stable across repeated merges and updates.
- Exported `events.json` + `events_data.json` expands to the same events as the current in-memory checkpointer path.
- Attachment refs from old events remain available after many later merges.

### Checkpointer Tests

Update existing tests to assert behavior, not private list internals:

- repeated fires accumulate cumulative output;
- same-cycle event updates serialize once with the final state;
- checkpointer unsubscribes on close;
- late truncated/no-provider seed still raises;
- late provider-backed seed streams/imports without calling the materializing `events` path.

### Bounded-Memory Regression Tests

- Emit many events into a bounded transcript with checkpointing enabled and assert `_Checkpointer` no longer has cumulative Python event/pool lists.
- Assert store counts grow while resident transcript counts stay bounded.
- Add an attachment regression where the event that introduced an attachment is evicted before checkpoint fire; the checkpoint export still contains the attachment.

## Risks and Mitigations

### Pool Index Mismatch

Pool refs are positional. If DB `id` values are not zero-based dense positions, exported refs will be wrong. Store explicit `pos` values and order by `pos`.

### Update Ordering Bugs

Event updates must preserve first-seen order while exporting latest content. Use `logical_id` primary key and `first_seq` stored only on first insert.

### Attachment Loss

Bounded transcript prunes attachments. The checkpoint store must retain cumulative attachment content independently.

### Export Memory Spikes

A naive export that builds full lists reintroduces the problem. Export JSON incrementally from DB cursors.

### Late Provider Seed

`list(ts.events)` is not acceptable under bounded mode. Add tests with a provider that raises on materializing `events()` and supports only streaming/suffix import.

### SQLite Lock Scope

Do not hold locks across awaits/restic. Use short merge transactions and short export transactions.

## Implementation Notes

- Keep the existing checkpoint file format initially.
- Keep the store private and checkpoint-specific.
- Prefer deterministic JSON serialization compatible with current `_json_dump()` output where practical.
- The store DB itself does not need to be included in the restic snapshot initially if exported files remain the checkpoint artifact.
- If exporting cumulative JSON becomes awkward or memory-prone, revisit using the SQLite DB itself as the checkpoint artifact; checkpointing is not live, so that remains negotiable.
