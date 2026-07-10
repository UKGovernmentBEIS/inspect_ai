# Framing: Pagination of Messages/Events Within a Sample

Status: framing/explanation — not yet a plan. Captures problem, current design, proposed direction, access-pattern inventory, and open questions.

## Problem

A single sample must support an essentially arbitrary number of messages and events. Today all data for a sample lives in one JSON entry inside the `.eval` zip. JSON parses sequentially from the top, which is at odds with the near-term requirement to serve windows/pages of messages and events. We remain committed to a single portable `.zip` file containing everything.

## Current design (verified)

- `.eval` = zip of zstd-compressed JSON entries: `header.json`, `summaries.json`, `reductions.json`, `_journal/start.json`, `_journal/summaries/{N}.json`, and **one entry per sample** `samples/{id}_epoch_{epoch}.json` (`src/inspect_ai/log/_recorders/eval.py`).
- The per-sample entry is the full `EvalSample`: `messages`, `events`, `scores`, `store`, plus two dedup structures:
  - `attachments: dict[hash, content]` — content-addressed (`attachment://<mm3hash>`), added to stop large content being duplicated in every turn's copy of the messages.
  - `events_data` — two pools of two currencies: `messages: list[ChatMessage]` (dedup of `ModelEvent.input`, same type as top-level `messages`) and `calls: list[JsonValue]` (raw provider-specific `ModelCall` request/response payloads — often the largest per-sample data; default reads leave them condensed via `resolve_attachments="core"`). `ModelEvent.input_refs` already range-encodes pool references as `(start, end_exclusive)` tuples.
  - **Double storage of the final conversation**: pooling applies only to events (`condense_model_event_inputs`); the top-level `messages` list is stored materialized in full (only images are attachment-extracted — long text stays inline, unlike the events walk). Since the final ModelEvent's input is ~the same list via pool refs, the last-turn conversation is effectively stored twice (`src/inspect_ai/log/_condense.py:147-212`). A unified id-addressed message sequence eliminates this.
- **Random access exists at sample granularity, not within a sample.** `AsyncZipReader` (Python) and `remoteZipFile.ts` (browser) range-read the central directory and individual entries. Within a sample the only relief is the ijson `exclude_fields` band-aid (skip top-level fields).
- **Completed-log reads are client-driven.** The view server has no per-sample JSON endpoint; the browser does its own zip random access via `/log-bytes` byte ranges or presigned S3 URLs, decompressing client-side (fflate/fzstd). static-http and VS Code backends ride the same path.
- **Live-run pagination already exists** and is unaffected: sample buffer (SQLite, cursor-based `get_sample_data(after_event_id=…)`) plus `.buffer/` segment zips for shared filesystems. The gap is the **at-rest** format.
- Write path: the recorder holds the zip open in append mode on a temp file; every flush rewrites the central directory and re-uploads the whole file. Large samples stress writes too, not just reads.
- Evidence of pain: browser hard-caps samples (512MB/2048MB uncompressed) and silently strips oversized events arrays (`clearLargeEventsArray`); the multi-frame zstd patch exists because single sample entries outgrew the browser decoder.
- Versioning: `LOG_SCHEMA_VERSION = 2`; forward tolerance via pydantic before-validators, no migration ladder. This restructure implies version 3.

## Proposed direction

Inspired by parquet row groups.

Terminology: a **sequence** is an ordered, homogeneous, index-addressed set of items (messages, events, calls), append-only during the run, physically stored as N chunk entries. (Deliberately not "stream" — that term is reserved for the live streaming/cursor path.)

- **Per-sample TOC** plus, for each high-scale sequence (messages and events, for now), a set of **chunk files** as sibling zip entries. Up to X items per chunk (X TBD).
- **Chunk names encode their index range** (`{start}-{end_exclusive}.pb`, zero-padded). Every reader must fetch the zip central directory anyway (byte offsets), so index→chunk is a binary search over sorted entry names — no TOC lookup, and no round trip that arithmetic naming would have saved. This makes the format **agnostic to chunking policy**: fixed X (the working assumption), size-based, or adaptive chunking all read identically; size-based becomes a writer-side tuning knob rather than a format change. The TOC therefore earns its keep only for per-chunk metadata (type counts, span/time ranges) — not for index mapping.
- **Chunks as zip entries preserves the architecture**: clients keep doing byte-range + central-directory reads; no new server endpoints required for completed logs.
- **Events reference messages by stable per-sample ids, range-encoded** (`[0..9873],[9875]`), never flat id lists — model-event inputs are prefixes-plus-delta, and flat lists are O(N²) across a transcript. (Precedent: `ModelEvent.input_refs` already uses `(start, end_exclusive)` ranges into the pool.)
- **Rehydration is a consumer concern**: the format guarantees stable ids and range-named chunks; consumers resolve which message chunks a window of events needs (via central-directory names) and fetch them independently. Interactive consumers hydrate lazily (virtualized rendering); non-interactive consumers wanting a fully hydrated final event genuinely need the whole conversation — no format fixes information content, APIs must not force hydration.
- **The message sequence likely subsumes the `events_data.messages` pool**: pooled messages and top-level `messages` are the same currency (`ChatMessage`) — they differ only in membership (pool = superset across all ModelEvent inputs; top-level = the final main thread). If messages are a first-class id-addressed sequence, ModelEvents reference message ids and the sequence *is* the pool. (Precedent: the buffer SQLite DB already has `message_pool` with autoincrement ids.) The `calls` pool is a different currency (raw provider payloads) and a likely **third sequence** — often the largest per-sample data. Whether `attachments` survives is open — its original motivation (cross-turn duplication) dies with the normalized pool; what remains is chunk-size hygiene for large inline blobs (deferred, coupled to size-based chunking).
- **Protobuf chunks are more than a nice-to-have.** Zip compresses entries independently; dedup pools remove *content* duplication but not JSON *structural* redundancy (key names, enum strings), which per-entry zstd currently recovers and which small chunks would forfeit. Protobuf eliminates that redundancy by construction, making small X viable. It requires a shared schema with TS + Python codegen (pydantic is currently the source of truth).

### Illustrative zip layout (per sample)

Naming, X=1000, and protobuf all illustrative; TOC location (inside shell vs separate entry) still open.

```
samples/
  1_epoch_1.json                 # the "shell" — everything small, cheap by construction:
                                 #   id, epoch, input, target, scores, metadata, model_usage,
                                 #   error, limit, timing, uuid...
                                 #   + sequence descriptors: {chunk_size: 1000,
                                 #       messages: {count: 48210}, events: {count: 103552},
                                 #       calls: {count: 9012}}
                                 #   + TOC (if colocated): per-chunk stats — event type counts,
                                 #       time ranges, span boundaries, id ranges
                                 #   NO messages / events / attachments / events_data
  1_epoch_1/
    messages/
      0000000000-0000001000.pb   # messages 0..999 (name = {start}-{end_exclusive}, zero-padded)
      0000001000-0000002000.pb
      ...
    events/
      0000000000-0000001000.pb   # ModelEvents carry range-encoded message ids and
      ...                        #   call-sequence indexes instead of inline copies
    calls/
      0000000000-0000001000.pb   # raw ModelCall payloads, one per model event
      ...
```

Notes:
- Chunk names encode their index range; index→chunk = binary search over sorted central-directory names (already fetched by every reader for byte offsets). End-exclusive matches the `input_refs` convention; adjacent names share their boundary value.
- The final conversation (`sample.messages`) becomes range-encoded ids into the message sequence — no double storage.
- `attachments`/`events_data` disappear as shell fields; their jobs are absorbed by the sequences (open question: blob extraction for chunk-size hygiene).
- Pattern 6 option (c) would add a skinny sibling per event chunk, e.g. `events/0000000000-0000001000.skel.pb`.

### Tension around X

Too big → overread; too small → chatty (one range request per chunk — same-sequence chunks are not byte-adjacent, so windows spanning k chunks cost k requests) and, with JSON, poor compression. Protobuf substantially relaxes the lower bound.

## Access-pattern inventory

From the view server and TS client (completed-log path):

| # | Pattern | Today | Demand on new format |
|---|---|---|---|
| 1 | Header / summaries / listing | Separate small zip entries | none |
| 2 | Sample "shell" (metadata, scores, usage, error) | Full parse or `exclude_fields` | Shell = slimmed sample entry; cheap by construction |
| 3 | Page messages by index window | Full load; virtualization is DOM-only | index→chunk arithmetic (core design) |
| 4 | Page events by index window | Same | Same |
| 5 | Tail / jump-to-last / follow | Full load | last chunk from total count (shell/TOC) |
| 6 | Transcript structure w/o content: event tree (`treeifyEvents`), outline, timeline | Walks entire events array before first render | **The hard one** — see below |
| 7 | Deep links (event uuid, message→event) | `findIndex` over full array | id→index mapping (TOC or per-chunk id ranges) |
| 8 | Event-type filtering | Client-side array filter | per-chunk type counts in TOC |
| 9 | In-sample search | Full scan client-side (scout offers server-side) | progressive per-chunk scan, or push server-side |
| 10 | Full hydration / export / Python full read | Whole file | read all chunks + reassemble (N reads) |
| 11 | Live streaming | Buffer cursors + segments — already paginated | unaffected; finalize-handoff could become chunk-aware |
| 12 | Python `read_eval_log_sample(exclude_fields, resolve_attachments)`, scout | ijson band-aid | shell + selective chunk reads |

### Pattern 6: structure without content

First render of a transcript needs something about *every* event (type, span_id, parent, timestamp). Options:

- **(a)** TOC carries per-event skeleton — honest but O(N); TOC itself needs chunking at ~1M events.
- **(b)** Sparse structure sequence: span begin/end + per-chunk type counts only; outline/timeline build from spans; tree hydrates per window. Requires viewer rework (progressive outline).
- **(c)** Column split, parquet-style: each event chunk gets a skinny sibling "skeleton" entry (type/span/timestamp, ~10-20 bytes/event in protobuf) fetched eagerly and in parallel; fat bodies fetched lazily.

Which option wins depends on whether full-outline-on-first-render is a UX requirement or progressive rendering is acceptable.

## Decided vs deferred

Decided (working assumptions):
- Flat chunked sequences for messages and events; chunk names encode `{start}-{end_exclusive}` index ranges (mapping via central-directory names); fixed X as writer policy; per-sample TOC.
- Stable per-sample ids; range-encoded event→message references; rehydration external to the format.
- Chunks remain zip entries; client-driven random access preserved.

Deferred:
- Value of X; size-based chunking (now just a writer-side policy choice — range-encoded names make readers agnostic).
- "Which messages" — `sample.messages` (final main thread) vs the full message pool (superset incl. every ModelEvent input). Buffer DB precedent favors the pool; deciding this also decides blob/attachment handling.
- Whether `attachments` survives (blob extraction / chunk-size hygiene).
- Mid-sequence state reconstruction (`StateEvent`/`StoreEvent` JSON Patch deltas are hostile to random access; keyframe snapshots are the classic fix).
- TOC location: inside the sample shell entry vs a separate entry.

## Open questions

- Pattern 6: full outline on first render required, or progressive acceptable? → decides TOC vs skeleton sequence (options a/b/c).
- In-sample search: allowed to become progressive or server-side (scout)?
- Protobuf: commit? Requires shared schema + TS/Python codegen; pydantic currently canonical.
- Write path: append chunks as the sample runs (converging recorder with the buffer/filestore segment mechanism) vs assemble at sample completion? Is full-reupload-per-flush in scope?
- Phasing/compat: dual-format period? migration tooling for v2 logs? reader fallback story.
