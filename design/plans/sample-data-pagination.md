# Framing: Pagination of Messages/Events Within a Sample

Status: framing/explanation — not yet a plan. Captures problem, principles, current design, proposed direction, access-pattern inventory, confounders, open questions, and next steps.

## Problem

A single sample must support an essentially arbitrary number of messages and events. Today all data for a sample lives in one JSON entry inside the `.eval` zip. JSON parses sequentially from the top, which is at odds with the near-term requirement to serve windows/pages of messages and events.

## Principles & working assumptions

Principles:

- **Scale target**: samples with 10M+ messages must be tractable.
- **Single portable `.zip`** containing everything remains the format.
- **Viewer access model**: paginated, filtered, index-based queries only — there is no "get all events" access pattern in the new design (sorting is unused). Full-fidelity reads (export, Python `read_eval_log`) remain as explicit bulk operations.
- **Data comes straight from the eval file** even when a server is present — the server just serves bytes.

Working assumptions (revisitable, not decided): flat chunked sequences for messages/events (likely + calls) as zip entries with client-driven random access; chunk names encode `{start}-{end_exclusive}`; fixed X as writer policy; JSON-array chunk encoding; per-sample TOC (likely = the precomputed timeline); stable per-sample ids with range-encoded references; rehydration external to the format.

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
- **The TOC is (likely) the timeline.** The timeline — today computed in-memory by the client on every sample load — is precomputed and embedded per sample, becoming the persisted data source for the tree view/outline. Two timeline implementations exist (Python `src/inspect_ai/event/_timeline.py`, TS `inspect-components/src/transcript/timeline/`) kept in sync via a shared JSON test suite. Computation is cheap (type comparisons, no content introspection); the event sequence is append-only, so it's rewritten (or incrementally updated) at sample boundaries. Index→chunk mapping stays in chunk filenames — the TOC is not needed for that.
- **Chunk names encode their index range** (`{start}-{end_exclusive}.json`, zero-padded). Every reader must fetch the zip central directory anyway (byte offsets), so index→chunk is a binary search over sorted entry names — no TOC lookup, and no round trip that arithmetic naming would have saved. This makes the format **agnostic to chunking policy**: fixed X (the working assumption), size-based, or adaptive chunking all read identically; size-based becomes a writer-side tuning knob rather than a format change. The TOC therefore earns its keep only for per-chunk metadata (type counts, span/time ranges) — not for index mapping.
- **Chunks as zip entries preserves the architecture**: clients keep doing byte-range + central-directory reads; no new server endpoints required for completed logs.
- **Events reference messages by stable per-sample ids, range-encoded** (`[0..9873],[9875]`), never flat id lists — model-event inputs are prefixes-plus-delta, and flat lists are O(N²) across a transcript. (Precedent: `ModelEvent.input_refs` already uses `(start, end_exclusive)` ranges into the pool.)
- **Rehydration is a consumer concern**: the format guarantees stable ids and range-named chunks; consumers resolve which message chunks a window of events needs (via central-directory names) and fetch them independently. (See confounder: the last page.)
- **The message sequence likely subsumes the `events_data.messages` pool**: pooled messages and top-level `messages` are the same currency (`ChatMessage`) — they differ only in membership (pool = superset across all ModelEvent inputs; top-level = the final main thread). If messages are a first-class id-addressed sequence, ModelEvents reference message ids and the sequence *is* the pool. (Precedent: the buffer SQLite DB already has `message_pool` with autoincrement ids.) The `calls` pool is a different currency (raw provider payloads) and a likely **third sequence** — often the largest per-sample data. Whether `attachments` survives is open — its original motivation (cross-turn duplication) dies with the normalized pool; what remains is chunk-size hygiene for large inline blobs (deferred, coupled to size-based chunking).
- **Chunk encoding: JSON first; protobuf deferred.** Ship with JSON-array chunks and revisit encoding only if measurement demands it. The tradeoff to carry in mind: zip compresses entries independently; dedup pools remove *content* duplication but not JSON *structural* redundancy (key names, enum strings), which per-entry zstd currently recovers and which small chunks forfeit — so JSON pressures X upward, and protobuf (which eliminates structural redundancy by construction) is what would make small X cheap. Protobuf's cost is a shared schema with TS + Python codegen (pydantic is currently the source of truth). Range-named chunks make encoding a per-entry concern (the extension says what's inside), so a later protobuf phase is additive, not a format break.

### Illustrative zip layout (per sample)

Naming and X=1000 illustrative; TOC location (inside shell vs separate entry) still open.

```
samples/
└── 1_epoch_1/
    ├── sample.json                    # the "shell" — everything small, cheap by construction:
    │                                  #   id, epoch, input, target, scores, metadata,
    │                                  #   model_usage, error, limit, timing, uuid...
    │                                  #   + sequence descriptors: {chunk_size: 1000,
    │                                  #       messages: {count: 48210}, events: {count: 103552},
    │                                  #       calls: {count: 9012}}
    │                                  #   + TOC = precomputed timeline/outline (if colocated;
    │                                  #       may instead be a sibling entry, e.g. timeline.json)
    │                                  #   NO messages / events / attachments / events_data
    ├── messages/
    │   ├── 0000000000-0000001000.json # messages 0..999 (name = {start}-{end_exclusive})
    │   ├── 0000001000-0000002000.json
    │   └── ...
    ├── events/
    │   ├── 0000000000-0000001000.json # ModelEvents carry range-encoded message ids and
    │   └── ...                        #   call-sequence indexes instead of inline copies
    └── calls/
        ├── 0000000000-0000001000.json # raw ModelCall payloads, one per model event
        └── ...
```

Notes:
- Everything for a sample lives under one `{id}_epoch_{epoch}/` prefix (shell included, as `sample.json`), so per-sample enumeration is a central-directory prefix scan.
- Chunk names encode their index range; index→chunk = binary search over sorted central-directory names (already fetched by every reader for byte offsets). End-exclusive matches the `input_refs` convention; adjacent names share their boundary value.
- The final conversation (`sample.messages`) becomes range-encoded ids into the message sequence — no double storage.
- `attachments`/`events_data` disappear as shell fields; their jobs are absorbed by the sequences (open question: blob extraction for chunk-size hygiene).
- Confounder 2 option (c) would add a skinny sibling per event chunk, e.g. `events/0000000000-0000001000.skel.json`.

### Tension around X

Too big → overread; too small → chatty (one range request per chunk — same-sequence chunks are not byte-adjacent, so windows spanning k chunks cost k requests) and, with JSON, poor compression. A later protobuf phase would substantially relax the lower bound.

## Access-pattern inventory

From the view server and TS client (completed-log path):

| # | Pattern | Accessed by | Today | Demand on new format |
|---|---|---|---|---|
| 1 | Header / summaries / listing | Log list + sample list UI: `remoteLogFile.readHeader`/`readLogSummary`, `/log-headers`, `/log-files` | Separate small zip entries | none |
| 2 | Sample "shell" (metadata, scores, usage, error) | Opening sample detail (header strip, Scoring/Usage/Metadata tabs); Python `read_eval_log_sample(exclude_fields)` | Full parse or `exclude_fields` | Shell = slimmed sample entry; cheap by construction |
| 3 | Page messages by index window | Messages tab: `ChatViewVirtualList` (`SampleDisplay.tsx`) | Full load; virtualization is DOM-only | index→chunk via range-named entries (core design) |
| 4 | Page events by index window | Transcript tab scroll: `TranscriptVirtualListComponent` → `VirtualList` | Same | Same |
| 5 | Tail / jump-to-last / follow | Auto-follow of running sample; `VirtualList` `followOutput`/`scrollToIndex` | Full load | last chunk from total count (shell/TOC) |
| 6 | Transcript structure w/o content: event tree, outline, timeline | First render of Transcript tab: `treeifyEvents` (`useEventNodes`), `useTranscriptTimeline`, `TranscriptOutline` | Walks entire events array before first render | **The hard one** — see Confounder 2 |
| 7 | Deep links (event uuid, message→event) | URL deep links / citations: `scrollToEvent` (`TranscriptViewNodes`), `resolveMessageToEvent` | `findIndex` over full array | id→index mapping (TOC or per-chunk id ranges) |
| 8 | Event-type filtering | Transcript filter menu: `eventFilter.filteredTypes` (`TranscriptPanel`) | Client-side array filter | per-chunk type counts in TOC |
| 9 | In-sample search | Transcript find-in-sample: `sampleSearch.findAllMatches`; scout `/scout/*` server search | Full scan client-side (scout offers server-side) | progressive per-chunk scan, or push server-side |
| 10 | Full hydration / export / Python full read | JSON tab, copy/download transcript (`SampleDisplay`), `readCompleteLog`, Python `read_eval_log` | Whole file | read all chunks + reassemble (N reads) |
| 11 | Live streaming | Running-sample view: `sampleStream.ts` cursors → `/pending-sample-data(-urls)`; `finalizeRunningSample` handoff | Buffer cursors + segments — already paginated | unaffected; finalize-handoff could become chunk-aware |
| 12 | Python `read_eval_log_sample(exclude_fields, resolve_attachments)`, scout | Programmatic analysis/scoring pipelines; scout transcript indexing | ijson band-aid | shell + selective chunk reads |

## Confounders

Three access patterns fight the chunked design; each needs an explicit stance.

### Confounder 1: the last page (hydration pulls in everything)

The common case for "open a sample" is the *end* of the transcript — and the last page of events almost always contains the final ModelEvent, whose input references essentially the entire conversation. Naively hydrating the last events chunk therefore means downloading every message chunk: pagination defeated by one event. What keeps it workable:

- The reference metadata itself stays tiny: range-encoded ids (`[0..N]`), never flat lists (which go O(N²) across a transcript).
- Interactive consumers are fine: the last chunk alone renders the frame; message ranges hydrate lazily at ceil(window/X) chunk fetches on scroll-into-view (the message list inside a model event is already virtualized).
- Non-interactive consumers (scoring pipelines, scout-style analysis, full-fidelity Python reads) that want the fully hydrated final event genuinely need the whole conversation — that is information content, and no format fixes it. The mitigation is API-shaped, not format-shaped: reading APIs must not force hydration.

### Confounder 2: structure without content (inventory pattern 6)

Why can't first render get by with just the event count? Count + estimated row heights is fully sufficient for a *flat* virtualized list (scrollbar extent + fetch-on-scroll — pattern 6 would collapse into pattern 4). Three consumers break count-only, in descending stringency:

1. **The main transcript is a flattened tree, not a flat list** (`treeifyEvents` → `flatTree`): every event carries `span_id`, rows are the depth-first flattening filtered by collapse state. A collapsed span elides its descendants, so row count ≠ event count and row↔event mapping needs the span membership of every event. This is the only consumer that needs *something about every event* — but only ~2 tiny fields (span_id, type), not bodies.
2. **The outline (left tree view)**: renders spans, which are sparse (span begin/end events, orders of magnitude fewer than events). A sparse span sequence serves it without per-event data.
3. **Timeline/swimlanes**: currently walks the full events array but is conceptually span-driven (rows = spans, extents = timestamps); the same sparse span data could serve it.

Structure metadata is also the elision index: per-chunk span coverage lets a collapsed 10k-event span skip fetching its chunks entirely.

**Resolution (direction): the precomputed timeline is the structure.** Rather than choosing among a TOC skeleton, a sparse span sequence, or a skeleton column, the existing timeline-building code (which already derives the semantic tree from events) is enhanced to also produce the outline, and both are persisted per sample — eliminating the fetch-all-events pattern for the tree view. The outline persisted is *maximal*: event filtering (e.g. hiding checkpoints) can only reduce it, and compaction-region selection is head/tail slicing, so every runtime view is a subset of the stored one. Remaining details: granularity (per-event leaves vs span-level + counts — decides persisted timeline size) and location (in the shell vs a sibling entry).

### Confounder 3: jump-to-end with variable-height rows

Ctrl+End / follow-output must position a scrollbar in a virtualized list whose row heights are unknowable without rendering. Today's approach — estimated heights cached and refined as rows render, error shrinking with row count — carries over; heuristics are unavoidable. Pagination doesn't make this worse (the shell's counts give the estimator its denominator with zero chunk fetches), but research is needed on how best-in-class virtualizers handle it.

## Open questions

(Working assumptions listed up top in Principles.)

- Value of X. (Size-based chunking is a writer-side policy choice — range-named chunks keep readers agnostic.)
- "Which messages" — `sample.messages` (final main thread) vs the full message pool (superset incl. every ModelEvent input). Buffer DB precedent favors the pool; deciding this also decides blob/attachment handling.
- Whether `attachments` survives (blob extraction / chunk-size hygiene).
- Mid-sequence state reconstruction (`StateEvent`/`StoreEvent` JSON Patch deltas are hostile to random access; keyframe snapshots are the classic fix).
- Timeline-as-TOC details: persisted granularity (per-event leaves vs span-level + counts) and location (inside the sample shell entry vs a sibling entry).
- In-sample search: allowed to become progressive or server-side (scout)?
- Chunk encoding (working assumption: JSON array per chunk; protobuf deferred until measurement demands it — its absence pressures X upward). JSONL was considered and set aside: its append-only strength doesn't apply (chunks are sealed write-once zip entries), and it trades away the single-call parse/validate fast path on the common whole-chunk case to buy partial parsing of overreads. Reconsider JSONL's complexity only if parsing of overread chunks proves material.
- Write path: append chunks as the sample runs (converging recorder with the buffer/filestore segment mechanism) vs assemble at sample completion? Is full-reupload-per-flush in scope?
- Phasing/compat: dual-format period? migration tooling for v2 logs? reader fallback story.

## Next steps

1. **Converter + render** (first goal): write a converter from existing log files to the new format and prove the browser client can consume paginated eval files — get real logs rendering — before investing in the live-write path.
2. Add a CLAUDE.md rule: any timeline code change must update both the Python and TypeScript implementations and their shared JSON test suite (sync has slipped before).
