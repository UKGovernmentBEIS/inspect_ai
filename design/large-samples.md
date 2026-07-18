# Arbitrarily Large Samples: Format, Viewer, and API Architecture

Status: **ratified design spec** — the output of the wayfinder effort
"[arbitrarily large samples in the viewer](https://github.com/epatey/inspect_ai/issues/1)"
(2026-07-18). Every section records a decision resolved on that map; section
headers link the resolving ticket. This document **absorbs and supersedes** the
`.eval2` framing doc (`design/plans/sample-data-pagination.md` on the
[`scale-prototype` branch](https://github.com/epatey/inspect_ai/tree/scale-prototype)) —
its problem analysis, measurements, and access-pattern inventory are carried
here; its draft mechanisms were ratified (with amendments) or replaced by the
map's tickets.

Reference workload: one sample with **337,351 events / 129,676 messages /
85,062 attachments** (~10B tokens, 963MB uncompressed) — the "monster" from
`mirror-code/ngnk_python`. Assume continued growth; the design targets 10M+
messages per sample.

---

## Confidence markers

Two classes of content, marked throughout:

- **Ratified** — at-rest format, read paths, viewer architecture for sealed
  logs, Python API. Grounded in a working converter, three real converted
  evals, and a render prototype driven against the monster.
- **⚠️ PROVISIONAL (live flow)** — everything about the live path: live-view
  unification ([#7](https://github.com/epatey/inspect_ai/issues/7)), the live
  byte source ([#9](https://github.com/epatey/inspect_ai/issues/9)), live
  skeleton/stats emission ([#19](https://github.com/epatey/inspect_ai/issues/19)).
  These decisions are low-confidence direction, and by construction of the
  phasing (read-first, [Phasing](#phasing--compatibility-18)) they stay
  unexercised until phase 2. **Re-validate — possibly revise — during
  live-path implementation.** They are recorded so phase-2 work starts from a
  coherent story, not so it treats them as settled.

## Core principles

1. **Merge to main early and often — no long-running branch. Absolute
   deal-breaker.** Code lands continuously but stays *unexposed* (hidden CLI,
   no public write path) until the format is frozen; hiddenness is what makes
   early merging safe. ([#18](https://github.com/epatey/inspect_ai/issues/18))
2. **Persisted-structure invariant**: anything persisted for structure scales
   with *structural spans*, never events (chunk-count-proportional is also
   acceptable). Beware the tool-span trap — one `tool` span per call is
   event-proportional in long agentic transcripts.
3. **Sealed logs = range reads only.** Consumption of a sealed log is purely
   byte-range reads + client-side zip central-directory parsing, on every
   backend. No server endpoint may ever be required for sealed-log features —
   anything the view server added would be an accelerator the static path
   can't have, so the format must not need it. ([#9](https://github.com/epatey/inspect_ai/issues/9))
4. **Persisted data is unopinionated**: the format stores structural and
   semantic facts (ids, ordinals, nesting, event types, names, counters) —
   never transformed output. Every interpretation (event-type filtering, turn
   synthesis, scoring collapse, labels, collapse defaults) is viewer-side
   policy applied at read time; policy evolves faster than stored logs.
5. **Chunking is writer policy, not format.** Readers infer chunk extents from
   names + the central directory; count-based, byte-target, or adaptive
   chunking all read identically.
6. **Derived data is regenerated, never migrated.** The skeleton and stats
   sidecar are deterministic functions of the event sequence; corruption or
   version skew is fixed by rebuilding them.

## Constraints (fixed at charting)

- **Serverless preserved**: partial event access via plain HTTP range requests
  (static hosting, S3, VS Code) — format-level chunking, not server-side
  pagination.
- **Old logs supported forever**: no on-the-fly conversion; feature-dropping
  above a size threshold is acceptable for old-format huge samples.
- **Scope axes**: events + messages + attachments (all token-linear).
  Store/scores stay whole-fetch.
- **Python API preserved**: `EvalSample.events`/`messages`/`attachments`
  become properties with getters — the hook to lazy-load and warn. New
  low-level read primitives are in scope; polished analysis APIs are not.
  Reading APIs must not force hydration (Confounder 1 below).
- **Write path**: incremental recorder in scope; bounding the eval process's
  own in-memory transcript is not (separate effort).

## The three confounders

Carried from the framing doc — the access patterns that fight a chunked
design, each with its ratified stance:

1. **The last page pulls in everything.** Opening a sample lands at the *end*
   of the transcript, and the final ModelEvent's input references essentially
   the whole conversation. Stance: references are range-encoded (never flat
   lists — those go O(N²)); the last chunk alone renders the frame; message
   ranges hydrate lazily on expand. Proven: the monster's final model event
   framed its 1,326-message input instantly from refs; tail hydration cost 1
   message chunk + 1 attachment chunk. Non-interactive consumers that want the
   fully hydrated final event genuinely need the whole conversation — that is
   information content; the mitigation is API-shaped (lazy reads), not
   format-shaped.
2. **Structure without content.** The transcript is a flattened tree (row
   count ≠ event count under collapse), the outline renders spans, the
   timeline reads span extents. Stance: the persisted span-proportional
   skeleton ([Skeleton](#structural-skeleton-5)).
3. **Jump-to-end with variable-height rows.** Estimate-then-correct
   virtualization, ratified with the ordinal-anchor amendment
   ([View-row pagination](#view-row-pagination-8)).

---

# Part I — At-rest format (ratified)

## Chunked on-disk layout ([#4](https://github.com/epatey/inspect_ai/issues/4), [#6](https://github.com/epatey/inspect_ai/issues/6))

The `.eval` zip gains an additive per-sample shape. A chunked sample lives
under a per-sample prefix; the zip **central directory is the offset index**
(every reader fetches it anyway; index→chunk is a binary search over
numerically-sorted entry names).

```
samples/
└── {id}_epoch_{e}/
    ├── sample.json          # the "shell" — everything small, cheap by construction:
    │                        #   id, epoch, input, target, scores, store, model_usage,
    │                        #   error, limit, timing, uuid…
    │                        #   + message_refs: [[0, 25], [26, 27]]  (final conversation,
    │                        #       half-open ranges into the message sequence)
    │                        #   + sequences: cumulative end-exclusive chunk boundaries
    │                        #       {messages: [1000, 2000, 2210], events: […],
    │                        #        calls: […], attachments: […]}  (last = sequence count)
    │                        #   NO messages / events / attachments / events_data / metadata
    ├── metadata.json        # sample.metadata (only when non-empty; user-controlled,
    │                        #   arbitrarily large — kept out of the shell)
    ├── skeleton.json        # span-proportional structural skeleton (below)
    ├── messages/
    │   ├── 0.json           # items [0, 1000)
    │   ├── 1000.json        # name = start index; extent = next chunk's start
    │   └── 2000.json
    ├── events/
    │   ├── 0.json           # ModelEvents carry range-encoded input_refs/call_refs
    │   ├── …                #   instead of inline copies
    │   └── stats.json       # per-chunk event stats sidecar (below)
    ├── calls/
    │   └── 0.json           # raw ModelCall payloads, one per model event
    └── attachments/
        ├── 0.json           # bare strings, referenced as attachment://<index>;
        └── 812.json         #   size-based chunking, so starts are irregular
```

Conventions:

- **Four flat, index-addressed sequences** per sample: `messages/`, `events/`,
  `calls/`, `attachments/`. A *sequence* is an ordered, homogeneous,
  index-addressed set of items, append-only during the run, physically stored
  as N chunk entries.
- **Chunk names carry the start index only** (`{start}.json`, no zero
  padding). Filenames have no range semantics; every range in *data* is
  half-open `[start, end_exclusive)`. The chunk holding index `i` is the one
  with the greatest start ≤ `i`; a chunk's extent is the next chunk's start;
  the last chunk's end is the sequence count from `shell.sequences`.
- **Encoding**: JSON-array chunks. Protobuf deferred behind a measurement
  trigger ([Levers](#measurement-triggered-levers)).
- Per-sample enumeration is a central-directory prefix scan; everything for a
  sample lives under its one prefix.
- Top-level entries (`header.json`, `summaries.json`, `reductions.json`) are
  unchanged; `_journal/` is unchanged.

**Chunk-size envelope** (research, [#3](https://github.com/epatey/inspect_ai/issues/3)):
1–8 MiB uncompressed per chunk (floor ~256 KiB, ceiling ~16 MiB), ≤ ~10k
members per archive. In-member random access was ruled out (deflate needs an
external index; zstd-seekable has no browser support), so **chunk boundary =
member boundary**. One-member-per-event ruled out (~28 MB central directory at
350k members; TTFB-bound per-event GETs). Defaults today: count-based 1000
items for item sequences, ~2 MiB byte-target for attachments (an oversized
item gets a chunk to itself). Default policy tuning (count vs byte-target) is
an open tunable, settled by measurement — not a format property.

### Pools and attachments ([#6](https://github.com/epatey/inspect_ai/issues/6))

- **The message sequence subsumes the `events_data.messages` pool.** Pooled
  and top-level messages are the same currency; the sequence *is* the pool,
  extended with final-conversation messages not already pooled. The shell's
  final conversation becomes range-encoded `message_refs` — this kills the
  double-stored final conversation. Sequence order is **event-appearance
  order**, not conversation order; consumers always go through refs. Existing
  `input_refs` remain valid (the pool is a prefix of the sequence).
- **Calls** are a third sequence (raw provider payloads — a different
  currency, often the largest per-sample data).
- **Attachments** are a fourth sequence of bare strings; **identity =
  sequence index** (`attachment://<index>`); content-hash dedup is demoted to
  write-time policy, never persisted. Attachments stay extracted (not inlined
  into events): content dedups *across containers* — measured 92MB of unique
  content inlines to 444MB (~5×) on petri.
- **Cross-sample attachment dedup rejected**: breaks prefix enumeration,
  sample-independent writes, and sample-level GC.

### References

Events reference messages/calls by stable per-sample indexes, range-encoded as
half-open pairs (e.g. `[[0, 9874], [9875, 9876]]`), never flat lists.
Rehydration is a consumer concern: the format guarantees stable indexes and
start-named chunks; consumers resolve which chunks a window needs via the
central directory and fetch them independently.

## Structural skeleton ([#5](https://github.com/epatey/inspect_ai/issues/5))

Where the viewer gets transcript *structure* (outline, timeline, tree
scaffolding, scrollbar extents under collapse) without reading events.
Client-side derivation was rejected: span events land in ~every chunk, so
deriving structure degenerates to a full event scan, and the honest cheap
variant (a spans-only projection) can't serve `gap_models` turn rows,
descendant-count scrollbar extents, or `hasVisibleContents`. Derivability
gives its safety anyway: the skeleton is a deterministic function of the
events sequence — distrusted skeletons are rebuilt, never migrated.

Sibling entry `skeleton.json` under the sample prefix. Sized by the invariant:
**skeleton ∝ structural span count (+ capped notables)** — no per-event entry
of any width. Measured on the monster: 60,900 raw spans → **673 structural**
after leaf-tool exclusion (98.9% excluded), 297KB skeleton.

```jsonc
{
  "version": 1,
  "counts": { "events": 250000, "models": 3400 },   // sample totals
  "spans": [
    {
      "id": "aB3x…",                // span_id (identity for span rows / collapse keys)
      "parent": null,               // index into this array
      "name": "react",
      "type": "agent",              // solver | agent | subtask | handoff | scorer | tool | …
      "begin": 1042,                // sequence index of the span_begin event
      "extent": [1042, 15200],      // [first, last] descendant event index (fetch elision;
                                    //   parallel spans may overlap — tolerated, correctness
                                    //   comes from span_id on fetched events)
      "t": ["2026-07-01T10:00:02Z", "2026-07-01T10:41:17Z"],
      "working": [12.5, 340.2],
      "events": 14158,              // descendant event count (incl. nested spans)
      "models": 212,                // descendant model-event count
      "gap_models": [5, 190, 0, 17],// turn placement (below)
      "children": { "state": 1 }    // direct-child event-type counts, sparse
    }
  ],
  "notables": [
    { "i": 9120, "span": 0, "type": "score" },
    { "i": 249995, "span": 0, "type": "checkpoint", "checkpoint_id": 3 }
  ]
}
```

Ratified mechanisms:

1. **Leaf-tool exclusion + size escape hatch.** A tool span with no child
   spans, no model events, and no notables is excluded and summarized in its
   parent's counters — this defuses the tool-span trap. Escape hatch: a leaf
   tool span with ≥ ~1 chunk (~1000) of descendant events is included anyway;
   at most events/1000 such spans exist (chunk-count-proportional, accepted
   class), and monster tool spans keep fetch elision + outline presence.
   Proven: 664 escape-hatch spans on the monster earned their keep.
2. **`gap_models` — the load-bearing counter.** A span's *items* are its
   direct-child structural spans and notables merged in sequence order;
   `gap_models[k]` = model-event count strictly between item `k-1` and item
   `k` (`len == items + 1`). This reproduces the outline's row layout (one "N
   turns" row per nonzero gap) without per-turn entries. Gap counts are
   **additive**: clients can suppress any item row by summing adjacent gaps,
   so escape-hatch spans and future row policy stay client-side. A gap row's
   anchor ordinal is the gap's lower bound.
3. **Notables: per-type first-N caps** (default ~1k, writer-policy knob) with
   per-type overflow flags — score events are *not* guaranteed sparse
   (intermediate scoring can emit one per turn). Outline degrades past-cap
   rows with an "N omitted" marker; `gap_models`/counters are computed against
   *persisted* items, so layout stays self-consistent.
4. **Field set**: `id, parent, name, type, begin, extent, t, working, events,
   models, gap_models, children` + sample totals. `flags` and agent-`desc`
   **cut** — no current consumer (verified: viewer default-collapse filters on
   spans key only on type+name; failed/agent/subtask filters target events,
   evaluated window-locally). Additive later via version bump + regeneration.
5. **Lifecycle**: written at sample finalize (live: re-emitted per flush,
   [#19](#live-skeleton--stats-availability-19-️-provisional)); no skeleton
   below the monolith threshold ([#17](#small-sample-monolith-threshold-17));
   producer = the Python timeline code with a **TS twin pinned by a shared
   JSON test suite**; the converter backfills. **Legacy step-only logs**: the
   producer maps step begin/end pairs to span-table entries — one skeleton
   contract, no legacy carve-out.
6. **Event identity = sequence index** (spans: `span_id`); uuids are never
   persisted outside event bodies (a uuid→index map is event-proportional,
   forbidden). Legacy `?event=<uuid>` deep links resolve by a one-time
   parallelizable chunk scan. The O(events) `elementIds` scroll-sync surface
   dies; sync = binary search over anchor ordinals.
7. **Parity oracle**: acceptance is differential — the legacy in-memory
   pipeline (frozen as an oracle) vs the skeleton-fed pipeline, compared
   row-for-row across converted real logs and synthetic fixtures × collapse
   states. Three divergence classes signed off (models nested directly under
   tool events → skeleton's structural row wins; cross-span consecutive score
   merging → two rows fine; "N turns" click anchor = gap lower bound). New
   divergences require explicit sign-off.

Parked (measurement-triggered): columnar skeleton encoding.

## Per-chunk event stats sidecar ([#5](https://github.com/epatey/inspect_ai/issues/5))

`events/stats.json` — events sequence only. Per chunk:
`{start, sparse type_counts, first/last event type + span_id}`. Deliberately
**separate from the skeleton**: stats are a function of chunking policy
(rechunking invalidates stats, not the skeleton). Lazy-fetched on first
filter/run-scan. Load-bearing for: filter pushdown (skip non-matching chunks
unread), run-extent scans, per-chunk row estimates, and O(1) chunk-edge
resolution (the first/last type+span_id is exactly sufficient for the
head-run-continuation rule — proven in the render prototype).

## Small-sample monolith threshold ([#17](https://github.com/epatey/inspect_ai/issues/17))

Chunking's costs (the +36% compression toll, per-entry overhead, chattier
reads) buy random access small samples don't need.

- **Per-sample granularity**: one log mixes monolith and chunked samples side
  by side. Denominated in **uncompressed serialized sample bytes**, known free
  at sample-finalize. Item counts rejected as proxies.
- **Monolith shape = today's `EvalSample` entry, unchanged**
  (`samples/{id}_epoch_{e}.json`). The existing parse path is reused
  wholesale. Accepted consequences: the format carries both reference dialects
  (quarantined per-sample); the live→sealed source swap for a small sample
  also swaps shape (chunked in flight → monolith at rest).
- **Finalize-time policy, never a start-time guess**: the in-flight live path
  is always chunk-encoded; the at-rest shape is chosen at sample-finalize when
  exact bytes are known (below threshold, seal serializes the in-memory
  sample; streamed live chunks are superseded).
- **Default = the shared 350 MiB full-fidelity constant** (same named
  constant as the viewer's full-fidelity bound — one number, not two).
  Invariant: **a new-format monolith can never hit the degradation ladder**
  (the ladder is an old-format-only concern). Trade-off accepted:
  tens-to-hundreds-of-MB samples keep today's whole-fetch open latency.
- Comparison: `chunk when uncompressed serialized sample bytes > threshold`.
  Writer config/env knob; **CI pins 0** (always chunk) so every small log
  exercises the chunked path; a "never chunk" debug sentinel exists.
- **Reader dispatch is structural, per-sample, off the central directory**:
  monolith = today's entry name; chunked = the `{id}_epoch_{e}/` prefix. One
  name form per sample. Monoliths get no skeleton — the viewer derives
  structure in memory as today; search treats them as fully-materialized
  corpus; lazy Python properties return already-materialized data, no warning.

## Named size constants

One table of spec'd named constants; all tunable without format consequences.
Python mirrors them so both surfaces degrade at the same sizes.

| Constant | Value | Measured on | Used by |
|---|---|---|---|
| `FULL_FIDELITY_BYTES` | 350 MiB | old format: events-array bytes post-fetch · new format: uncompressed serialized sample bytes at finalize | old-format events-cleared tier trigger; monolith-vs-chunk threshold; Python hydration warning |
| `SAMPLE_CLEAR_BYTES` | 512 MiB | old format: member bytes post-fetch · Python: member `uncompressedSize` pre-parse | old-format events-cleared tier (total); Python pre-parse warning |
| `SAMPLE_REFUSE_BYTES` | 2 GiB | member `uncompressedSize`, pre-fetch (central directory) | viewer refuse tier (old format only) |

## Compression measurements & levers

Measured (petri, 470 samples): chunked conversion costs **+36% compressed**
(37.7 → 51.1 MB) — the direct price of per-entry compression scope severing
cross-entry matching. Uncompressed *drops* 332 → 292 MB (dedup working), but
dedup and zstd remove the same redundancy. Null results: attachment chunk
target size (2/8/32 MiB) makes no difference; zstd level 9 saves only ~7%.
Comingling measurements: all four sequences −27.6%, **events+attachments alone
−24.4%** (the affinity is almost entirely events↔attachments), messages+X
negligible — full comingling rejected (messages are ~4% of bytes;
time-interleaving smears a message window across every chunk).

### Measurement-triggered levers

Parked, additive, explicitly *not* built now. Each reopens only on an observed
problem:

| Lever | Trigger | Effect |
|---|---|---|
| Protobuf chunk encoding | the +36% toll proves material | removes JSON structural redundancy; cost = shared schema + TS/Python codegen |
| Trained zstd dictionaries | same | pre-warms every entry; needs browser fzstd support |
| Events+attachments comingling | same, or snippet-hydration latency | −24.4%; costs event-chunk overread from the Messages tab |
| Attachment inline-threshold bump (`len > 100`) | snippet-hydration latency | more smalls arrive with the event |
| Columnar skeleton encoding | skeleton size | parallel arrays, RLE/zstd-friendly |
| Durable client chunk cache (IndexedDB) | re-fetch cost observed | additive below the byte store; contract unchanged |
| Worker-side viewer data layer | observed main-thread jank | decoded window lives in a worker; render-ready rows shipped out |
| Precomputed search-index sidecar | scan latency at extreme scale | additive sidecar; drifts from renderer text — same posture as protobuf |

---

# Part II — Live path (⚠️ PROVISIONAL)

Everything in this part is provisional direction (see
[Confidence markers](#confidence-markers)): spec'd now, exercised only in
phase 2, expected to be re-validated and possibly revised then.

## Live-view unification ([#7](https://github.com/epatey/inspect_ai/issues/7))

**Unified encoding, consolidate at seal.** Live segments and the finalized
format become one encoding; the sealed zip remains the single final artifact.

1. **Segments carry final-format bytes.** Live segment zips (`segment.{N}.zip`,
   one PUT per flush as today) contain chunk members with their *final* names
   and encoding. Today's `SampleData`/pool/monotonic-cursor shape is retired.
2. **Supersede-tail.** A sample's partial tail chunk is rewritten under its
   final start-index name on each flush; the latest segment wins for a
   duplicated member name. Chunk boundaries remain pure writer policy — flush
   cadence never dictates them.
3. **Protocol-level unification, not storage-level.** SQLite
   (`buffer/database.py`) stays the sole local live store and the
   crash-recovery source; the local view server *synthesizes* chunk-protocol
   responses from it. Real segment objects exist only when `log_shared`. The
   viewer gets **one chunk decoder** with **two byte sources**:
   server-synthesized locally, static range reads remotely.
4. **Manifest = live chunk directory.** Per sample, per sequence:
   `(start_index, segment_id, member_offset, member_size)`,
   supersede-resolved by the writer (only winning versions listed). Client
   cursor = per-sequence next index; resolution to bytes is one HTTP range
   read per chunk — no zip-CD parsing, no post-filtering. After seal, the
   final zip's central directory plays the identical role: same client logic,
   two directory encodings. The four `last_*_id` cursors and the
   OR-filter/post-filter protocol are retired.
5. **Sidecar rule.** Everything span- or chunk-proportional that a late-joining
   reader needs is a live supersede-member: `skeleton.json` and the stats
   sidecar (see [#19](#live-skeleton--stats-availability-19-️-provisional)).
   Completion-semantic artifacts are seal-only: `sample.json` shell
   (`message_refs` only exist at completion; the manifest summary serves the
   live role), `metadata.json`, reductions, header.
6. **Seal path: local accumulator, seal-only remote upload.** The recorder
   keeps the growing zip locally; completed samples are appended as chunk
   members streamed from SQLite (memory-bounded — a huge sample is never held
   whole). In shared mode the per-flush whole-file re-stream is
   **eliminated**: a tiny start-stub `.eval` (spec/plan, status `started`) is
   written remotely at `log_start` (crash discovery + eval-set retry
   classification keep working), and the sealed file is uploaded once
   (multipart) at `log_finish`. Segments are purely a live transport; by
   construction of supersede-tail their chunk bytes are identical to the
   sealed file's.

Crash recovery is unchanged (SQLite source); remote segments additionally hold
final-format bytes up to the last sync as a redundancy bonus. The writer-side
attachment hash→index dedup table lives in the sample-buffer SQLite (a bounded
table degrades to duplicate storage, never incorrectness). Rejected: two
formats / two viewer paths (pool elimination obsoletes today's segment shape
anyway); no-consolidation (S3 immutability + no central directory while
growing; a directory-of-objects final format contradicts the layout decision).

## Live skeleton & stats availability ([#19](https://github.com/epatey/inspect_ai/issues/19))

**Same artifacts, re-emitted per flush; seal = the existing source swap. No
second structure format, no client derivation, no special cases.**

1. **Writer re-emits the full skeleton at each flush** — a `skeleton.json`
   member in the live segment, superseded per flush, manifest-pointed. No
   incremental-update protocol: the skeleton is span-proportional and small
   (KBs typical, <1MB pathological); how the writer computes it (recompute vs
   incremental) is writer-internal. Rejected: client-side derivation
   (structurally unsound under the window cap — the head may never be
   fetched); a degraded manifest-carried partial structure (a second, weaker
   format).
2. **Stats sidecar treated exactly like the skeleton** — full re-emit per
   flush, superseded, manifest-pointed — covering all sealed chunks plus the
   current partial tail. Head row accounting therefore works pre-seal
   (scrolling back up a running monster gets real per-chunk row estimates),
   and one encoding/decoder serves live and sealed stats.
3. **Seal handoff = nothing but the source swap**: invalidate and refetch
   skeleton + stats through the swapped byte source, like chunk bytes. The
   finalize-written versions are supersets of (typically identical to) the
   last live emission — same producer, same append-only events. The client
   never accumulates or merges structure, so nothing reconciles; UI state
   survives on stable keys (collapse = `span_id`, scroll anchors = event
   ordinals).

---

# Part III — Viewer architecture (ratified for sealed logs)

Proven end-to-end by the render prototype
([#8](https://github.com/epatey/inspect_ai/issues/8),
[proto/eval2-render](https://github.com/epatey/inspect_ai/tree/proto/eval2-render/prototypes/eval2-render)):
open-at-end of the monster = 9 requests / 3 of 338 event chunks; a full
session (2 deep jumps, fling-scroll, collapse/expand, type filter) touched
17/338 chunks; outline = zero event reads; collapsing the 337k-event span =
free.

## Client data contract

The complete surface the transcript + outline consume — no server, no other
index:

1. `shell.sequences` (chunk boundaries per sequence) + `message_refs`
2. `skeleton.json`
3. `events/stats.json`
4. `getRange(sequence, [lo, hi))` — chunk-cached random access, all four
   sequences
5. `readEvents(from, {types, max})` / `FilteredCursor` — the one nontrivial
   primitive

## Data-loading architecture ([#9](https://github.com/epatey/inspect_ai/issues/9))

1. **IndexedDB stays listings-only.** Chunk/sample-body data is never
   persisted client-side. (Durable chunk cache = parked lever.)
2. **Two-tier in-memory cache, scoped per sample, dropped on deselection.**
   Below: a **framework-free chunk-byte store** (precedent: `fetchEngine`'s
   framework-free core) owning `getRange` over all four sequences, raw-buffer
   byte-budget LRU (generous knob, ~256MB class), request dedup. Raw
   ArrayBuffers live outside the V8 heap cage; parsed objects are the scarce
   resource.
3. **Parsed tier = bidirectional `useInfiniteQuery`**: page = event chunk
   (chunk = decode = fetch unit), `pageParam` = chunk index,
   `getPreviousPageParam` for upward growth, `maxPages` = the window cap
   (far-end eviction; scroll-back re-parses from the byte store, no
   re-download). Deep jump = re-anchored queryKey
   (`[sample, filter…, anchorChunk]`); old anchors age out via gcTime. Page
   queryFn = decode walk + **synchronous attachment resolution** — a page is a
   materialized row-window slice; the UI never sees an `attachment://` ref.
   Boundary: event-body refs only; `input_refs` message ranges stay lazy
   (hydrate on expand — Confounder 1).
4. **⚠️ PROVISIONAL — live = a second byte source**, not a generalized
   `sampleStream`: manifest polled on the existing 2s/10ms-catchup cadence →
   same chunk store; tail-following = `fetchNextPage`; supersede-tail =
   invalidation of affected tail chunks (byte store + query pages), never
   in-place patching; seal = byte-source swap under the same store — chunk
   identity is preserved (final names), so nothing refetches.
   `sampleStream.ts` + the four-cursor protocol survive for **old-format live
   samples only** (lifetime = phasing).
5. **Sealed = range-reads-only** (core principle 3). All three backends
   (view-server `/log-bytes`, static-http, VS Code) work day one untouched.
   Live adds one method pair (sample manifest + segment bytes) mirroring
   today's proxy/presigned-direct split with the existing probe/fallback state
   machine; vscode inherits proxy via the tunnel; static keeps its no-live
   stance.
6. **Worker decompress, main-thread per-chunk parse.** Chunks flow through the
   existing zstd-worker path; per-chunk `JSON.parse` (1–8 MiB ⇒ ~5–40 ms)
   stays on the main thread — shipping parsed objects from a worker is a
   structured clone costing the same order. (Worker-side data layer = parked
   lever.)
7. **The UI boundary moves from events-array to row-window.** The data layer's
   product is materialized row windows + row-count estimates with bounded
   local corrections + ordinal scroll coordinates (`rowIndexForOrdinal`
   re-anchoring); the outline consumes the skeleton only. Consequence, named
   honestly: a **forked list-model layer** at the VirtualList level (shared
   per-event row renderers, second window model); fork lifetime = the phasing
   plan. Placement: new framework-free module under
   `apps/inspect/src/log_data/`, third source in `deriveSampleData`'s path
   selection.
8. **Filter counts: exact digits, approximate pixels.** Displayed numeric
   counts (filter badges, outline counters) are exact sums from the stats
   sidecar; scrollbar/row-space extents are estimate-then-correct — rows ≠
   events (runs, collapse elision), so exact extents are unobtainable from
   stats regardless, and an approximate pixel is invisible where an
   approximate digit reads as a bug.

## View-row pagination ([#8](https://github.com/epatey/inspect_ai/issues/8))

View rows are not events: transformations filter events out, merge runs into
one row, and elide collapsed subtrees — so "fetch 20 rows" has no fixed answer
in raw-event units, and a raw window can split mid-row. The outline is
untouched (its rows come entirely from the skeleton). I/O invariant: **reads ∝
rows emitted, never events skipped**. Ratified as drafted with three
amendments (all proven in the prototype).

### Layer 1 — filtered cursor read (the primitive)

`readEvents(fromOrdinal, {types, max}) → {events: [{ordinal, raw}…], next}` —
a cursor read over the flat event sequence where **`max` counts *surviving*
events**, with type filtering pushed down into the reader (per-chunk type
counts let it skip non-matching chunks unread). This fully absorbs density
(10k logger events between two surviving rows cost ~nothing); callers never
estimate raw↔surviving ratios. A thin `FilteredCursor` wraps it with
`peek()`/`next()`/`seek(ordinal)` over an internal buffer.

### Layer 2 — the decode walk

Produce rows by walking surviving events; the skeleton lets the walk *seek*
(zero reads) and runs *coalesce*:

```ts
// filter always force-includes span_begin/span_end — structure drives the
// walk and is only conditionally a row, never subject to the user's filter
cursor = FilteredCursor(startOrdinal, userFilter ∪ {span_begin, span_end})

while (rows.length < n && !cursor.done) {
  ev = cursor.peek()
  if (ev is span_begin) {
    span = skeleton.byBeginOrdinal(ev.ordinal)
    if (!hasVisibleContents(span, userFilter)) cursor.seek(span.extent[1])  // filterEmpty, from counters
    else if (isCollapsed(span.id)) { rows.push(spanRow(span, collapsed)); cursor.seek(span.extent[1]) }
    else                           { rows.push(spanRow(span, expanded));  cursor.next() }
  }
  else if (ev is span_end) cursor.next()                       // no row
  else if (isRunType(ev)) rows.push(runRow(takeRun(cursor, ev)))
  else { rows.push(eventRow(ev, skeleton.depthAt(ev.ordinal))); cursor.next() }
}
```

A collapsed span covering 1M events is one row and one seek. Starting
mid-stream seeds depth from `skeleton.spanStackAt(k)` (binary search over
extents — giant spans never fetched to know where you are inside them).

### The three amendments (ratified)

1. **Row accounting per event chunk**, not a global segment tree: each chunk
   carries an estimated surviving-row count (from stats, minus collapse
   elision, runs guessed at average length); decoding corrects it to exact.
   Corrections are bounded and local; prefix sums over ≤~10k chunks are
   trivial. The chunk is decode unit = fetch unit.
2. **No reversed cursor.** Upward pagination = decode the chunk above via the
   same forward walk + the **head-run-continuation rule**: if the previous
   chunk's stats `last` (type+span_id) matches this chunk's `first` for a run
   type, the head run is consumed rowless (it belongs to the chunk where it
   starts). The stats sidecar's first/last fields are exactly sufficient — O(1)
   edge resolution.
3. **Ordinals are the scroll coordinate system.** Row-count corrections above
   the viewport shift content; the fix is an ordinal anchor — track the
   topmost visible ordinal, re-scroll to `rowIndexForOrdinal(anchor)` on
   correction. Not perceptible in normal scrolling; cold jumps settle in one
   correction.

### Runs — the mid-character case, bounded

Merge runs (retry groups, sandbox runs) are the only decode units that can
straddle arbitrarily many chunks. Two properties bound them: (1) run
membership is decidable from type + span facts alone, so `takeRun` finds a
run's extent by scanning chunk *statistics* — only the 1–2 mixed edge chunks
are read; (2) a run's row needs O(1) representative events, never its
contents. **Binding constraint on future transforms: every row-merging rule
must be decidable from type/span facts available in chunk stats — never from
event payload contents.** A payload-dependent merge rule silently reintroduces
unbounded lookback.

## Transcript search ([#10](https://github.com/epatey/inspect_ai/issues/10))

**Progressive scan-as-you-search is the only mechanism.** Rejected: a
server-side search endpoint (redundant once scan exists; violates
range-reads-only); a precomputed in-log index (token-linear cost; drifts from
the renderer's evolving notion of "the text of an event"; revisitable as a
parked lever); search over replicated IndexedDB (dead — listings-only).

- **Scope**: the find band (Ctrl-F) only. The scout-backed Search Panel is a
  separate server-dependent subsystem and keeps working where scout exists.
  One architecture for serverless and server-backed.
- **Corpus — renderer-aligned**: the scan runs over *materialized* events
  (chunk decode + synchronous attachment resolution) through the renderer's
  own text extraction (`extractEventFields` / `messageSearchText`). Find
  matches exactly what the user can see; attachment content is searched
  because rendered text includes it. Raw-stored scan rejected (misses
  attachment content, matches invisible JSON).
- **Execution — dedicated scan worker, scan-and-discard**: fetches chunk
  bytes, decompresses, parses, extracts, matches, drops the bytes.
  Read-through of the render path's chunk-byte store for already-cached
  bytes, **never writes into it** — scan traffic must not evict the viewing
  window. Extractors must be worker-importable (implementation-time check).
- **Navigation — cursor-anchored directional scan**: "next" scans forward
  chunk-by-chunk from the cursor's chunk, "prev" backward; first hit in the
  requested direction resolves navigation immediately. Hit identity =
  (sequence index, occurrence-within-item); hit → ordinal → chunk jump via the
  re-anchored-queryKey machinery, then the existing settle-and-highlight DOM
  dance. No-wrap semantics preserved.
- **Counter — progressive**: after navigation is served, a lower-priority
  background sweep walks remaining chunks; "n of ≥m — scanning…" settles to
  exact. Gated on explicit search action (Enter / first next-prev), never per
  keystroke. The worker keeps a per-term, per-chunk match table (ordinals +
  counts) memoizing counting and repeat navigation.
- **Sequence-generic**: one scanner parameterized by (sequence, extractor) —
  transcript = (events, event extractor), chat = (messages,
  `messageSearchText`). Whole-fetch tabs (Scoring/Metadata/JSON) keep plain
  `window.find`.
- **⚠️ PROVISIONAL — live**: the scanner consumes the same two-byte-source
  abstraction as the render path — tail chunks extend the match table
  incrementally, superseded chunks invalidate their entries, seal is an
  invisible source swap.

---

# Part IV — Python API (ratified)

## Read primitives & `EvalSample` back-compat ([#12](https://github.com/epatey/inspect_ai/issues/12))

**Lazy `EvalSample`** (back-compat surface):

- `events` / `messages` / `attachments` become hydrate-on-first-access
  properties with **transparent materialization** — the full list is always
  returned — plus a **warning above the mirrored byte thresholds**
  (`FULL_FIDELITY_BYTES` / `SAMPLE_CLEAR_BYTES`).
- **Detached hydration**: the sample holds log path + shell only; first access
  opens an ephemeral reader (reusing a caller-supplied `reader=` if open),
  fetches the sequence's chunks, caches, closes. No lifetime obligations;
  picklable.
- **Pydantic**: readers return a private `EvalSample` subclass
  (isinstance-compatible; no new public type; eval-runtime construction
  untouched). `model_dump`/`model_dump_json` **hydrate** (same warning) —
  `read → dump/write_eval_log` round-trips at full fidelity.

**New primitives — a sample reader object**:

- `open_sample_reader(log, id, epoch)` — context-managed; **async-native core
  + sync facade** via `run_coroutine` (the existing
  `read_eval_log_sample`/`_async` idiom). Central directory + shell parsed
  once.
- Roster: `shell`; `events/messages/calls/attachments(start, end)` half-open
  range reads fetching only covering chunks; `iter_events()`/`iter_messages()`
  chunk-buffered iteration (memory bounded by one chunk); `skeleton()`.
- Deliberately excluded: span-scoped convenience (compose `skeleton()` → range
  read) and by-uuid lookup (inherently a scan; legacy-link resolution is
  viewer-side).
- **Resolution defaults mirror the TS contract**: `resolve_attachments=True`,
  `resolve_input=False` — `input_refs` is already a legal schema state on
  main; full hydration is one explicit knob away. Default reads are
  Confounder-1-safe.

**Existing APIs on chunked logs**:

- `read_eval_log(samples=True)`, `read_eval_log_samples`,
  `read_eval_log_samples_by_id` → lazy samples; zero eager cost.
- `resolve_attachments=` keeps its documented default (`False` → events carry
  `attachment://<index>` refs and `.attachments` materializes as the
  `{index: content}` dict — manual resolution preserved; deliberate asymmetry
  with the new reader's `True` default).
- `exclude_fields=` honored at the lazy layer: excluded sequences never
  hydrate.
- Sync property getters bridge via `run_coroutine`, inheriting existing
  nested-loop behavior — no new bridging semantics.

## Degradation policy for old-format huge samples ([#13](https://github.com/epatey/inspect_ai/issues/13))

**Ratify, don't redesign**: the viewer's existing three-tier ladder is the
policy of record for old-format (`.eval`) samples. New-format samples never
hit it (monolith invariant + chunked reads).

| Tier | Trigger | Behavior |
|---|---|---|
| Full | member ≤ `FULL_FIDELITY_BYTES` | everything loads |
| Events cleared | events > `FULL_FIDELITY_BYTES` or total > `SAMPLE_CLEAR_BYTES` | full member fetched, `events` byte-stripped before parse; transcript tab shows the existing "events removed — use Messages tab" banner; messages/scores/metadata intact |
| Refused | member > `SAMPLE_REFUSE_BYTES` (checked pre-fetch against the central directory) | detail view errors; the list row (from summaries) stays visible |

- **Refuse-tier UX**: a hard error — no summary-stub detail view. The message
  is improved: states the sample's actual size and points at the Python API as
  the escape hatch. **It does not mention offline conversion** (the converter
  stays hidden per the phasing decision; copy revisited if that changes).
- **Python: warn, never fail.** Readers check member `uncompressedSize`
  (free — central directory) against `SAMPLE_CLEAR_BYTES` pre-parse, warn in
  the same style as the hydration warning, and proceed. No hard cap — Python
  has no browser memory cliff. Old-format samples remain eager-parse (no lazy
  subclass).
- **Rejected**: stream-parse-first-N-events (a mechanism redesign for a legacy
  edge case). **Out of scope**: `.json`-format logs (whole-log single file, no
  caps today; huge ones remain best-effort).
- Derived consequences: the events-cleared tier still downloads the full
  member (messages share it — inherent to the old format, accepted); search on
  a degraded old sample covers only what's in memory; the old-format live path
  is not governed by this policy.

## Downstream tooling matrix ([#14](https://github.com/epatey/inspect_ai/issues/14))

Vocabulary: **works-as-is** / **works-as-is + warning** (accepted RAM cost;
the hydration warning is the guard) / **needs rework** / **deferred** (open
issue, resolved outside this effort).

| Consumer | Verdict | Basis |
|---|---|---|
| `inspect log list` / `headers` / `export-config` / `dump --header-only` | works-as-is | header/filesystem reads only |
| eval-set directory scan + retry decisions | works-as-is | headers + summaries only |
| eval-set/retry lazy sample source (`read_from_file`) | works-as-is | per-sample reads; strictly improved by lazy samples |
| `eval_retry` whole-log read | works-as-is | lazy samples keep residency at shells until re-log |
| In-repo scanners (`task/scan.py`) | works-as-is | operate on in-memory samples as they complete |
| `resolve_attachments` | works-as-is | semantics fixed by the API decision; transient ~2× copy inherits warnings |
| `inspect log dump` | works-as-is + warning | hydrates at serialization; output is inherently sample-sized |
| `inspect log convert` | works-as-is + warning | `--stream N` bounds cross-sample concurrency only; one monster sample fully materializes |
| Dataframes (`samples_df`, `messages_df`, `events_df`) | works-as-is + warning | serial path holds all logs hydrated concurrently — unchanged; chunk-streamed extraction noted as future improvement |
| Crash recovery | **needs rework, mechanism deferred** | coupled to one-member-per-sample identity + hand-written inline-events JSON; the seal-from-SQLite path means a crashed chunked local log has no flushed samples — "recovery = run the seal against the surviving buffer" is the candidate shape. Old-format recovery unchanged. |

Investigation ground truth recorded with the matrix: viewer `/log-edit` is
tags/metadata only (header-only both ways; score edits have no viewer
endpoint); no event-level streaming exists anywhere today — the sample is the
universal granularity unit; `exclude_fields` (ijson skip) is the only
sub-sample mitigation and is not CLI-exposed.

## Mid-sequence state/store reconstruction ([#16](https://github.com/epatey/inspect_ai/issues/16))

**No keyframes; deltas stay as-is.** Ground truth: nothing reconstructs state
at arbitrary event k — anywhere. The viewer's `StateEventView` renders a
purely local single-event diff from the event's own `changes`; the only
whole-store UI is fed by the shell's final `store` field; Python has exactly
one replay site (`store_from_events()`, terminal-store-only, zero internal
callers); dataframes do no state reconstruction.

- Per-event diff rendering is self-contained, so windowed reads render
  state/store events with zero prior context.
- Keyframes rejected for now: event-proportional derived data serving zero
  consumers. Recorded as future-additive writer policy if a "state at point k"
  UI ever materializes (additive-chunk design ⇒ no format break).
- `store_from_events` stays as-is: callers pass `sample.events` → transparent
  hydration + size warning. No streaming variant (analysis APIs out of scope).

## Known-expensive operations

Standing section: Inspect features that are inherently inefficient or
expensive under the chunked format. Later work appends here.

1. `store_from_events` / `store_from_events_as` — full hydration + O(n)
   replay; a chunk-streamed variant is possible but unbuilt.
2. Any future "state/store at event k" — no keyframes; replay from sequence
   start.
3. Legacy `?event=<uuid>` deep links — one-time parallelizable chunk scan
   (uuids are not persisted outside event bodies).
4. Score edits / `invalidate_samples` — full-log parse + whole-zip rewrite
   (degraded with warning) until the deferred representation question is
   resolved ([Open issues](#deferred-open-issues)).
5. Reused-sample carry-over in eval-set/retry — full hydration + re-condense +
   rewrite per reused sample, until the deferred byte-copy candidate is
   pursued.
6. Remote tag/metadata edits — whole-zip in-memory rewrite with
   decompress/recompress, until the deferred candidates (raw member copy,
   `UploadPartCopy`) are pursued.

---

# Part V — Phasing & compatibility ([#18](https://github.com/epatey/inspect_ai/issues/18))

**Core principle (restated from the top because it governs everything
below): merge progress to main early and often — no long-running branch.
Code lands continuously but stays unexposed until the format is frozen.**

## Phases (milestone-gated, no dates)

1. **Phase 1 — read support everywhere, no writer.** Chunked-sample reading
   diffuses into all eval-reading surfaces (inspect Python API, inspect
   viewer, Scout, Scout viewer, others). Testing rides the converter over real
   converted logs; the live path is knowingly unexercised in this phase.
2. **Phase 2 — opt-in write, after upgrade soak.** The write path is exposed
   opt-in (mechanism deferred to implementation: env var vs CLI/eval option —
   both candidates recorded); trial users; the live/seal path is proven here
   (and the ⚠️ PROVISIONAL sections re-validated).
3. **Phase 3 — default flip**, only after the opt-in soak.

## Format gate

**No version bump: `.eval` extension, `LOG_SCHEMA_VERSION` stays 2.** Chunked
samples are an additive per-sample shape detected structurally
(central-directory dispatch). Ground truth: the `.eval` read path deliberately
ignores the version field today (leniency norm); the `.json` reader hard-fails
on version > 2. `.eval2` was prototype-only naming. **Marked follow-up with
JJ**: whether the version field should ever gate this / why `.eval` reads
ignore version.

## Converter

`inspect log convert-eval2` (naming will change with the `.eval2` name's
retirement) stays on the CLI, **hidden long-term** — an internal/CI testing
vehicle only; no public exposure until the format is frozen (no supporting
intermediate format versions in the wild). It grows a hidden
threshold/force-chunk knob so CI can produce chunked small-sample corpora
without a writer (mirrors CI-pins-0). Consequence: the >2GB refuse-tier
message does **not** mention conversion for now.

## Forward compatibility

1. Stale installs meeting a chunked log **fail loudly by construction** —
   chunk entries break their `samples/*.json` sample enumeration; nothing
   silently drops samples. No retrofit; mitigation is the read-first phasing
   soak.
2. Updated readers handle both per-sample shapes transparently; version
   ignored pending the JJ follow-up.
3. The chunked shape is `.eval`-only; the `.json` log format never chunks (its
   existing version check stays).
4. Old logs readable forever (charting constraint).

## Proposed slicing into implementation efforts

A proposal to seed planning, not a commitment. Ordering follows the phases;
within phase 1 the efforts are largely parallel after A.

**Phase 1 (read everywhere):**

- **A. Format core + skeleton producer (Python).** Entry naming/dispatch
  (`format.py` lineage), the named-constants table, the skeleton + stats
  producers on the timeline code, the shared Python/TS JSON test suite, the
  parity oracle harness, converter hardening (backfill skeleton/stats, hidden
  force-chunk knob, `.eval2` naming retired). CI corpora generation.
- **B. Python read primitives.** The sample reader, lazy `EvalSample`
  subclass, warnings, existing-API integration, old-format pre-parse warning.
  Depends on A.
- **C. Viewer data layer + windowed transcript.** Chunk-byte store, infinite
  query tier, decode walk + FilteredCursor, row-window list-model fork,
  outline/timeline from skeleton, filter counts, refuse-message copy update.
  Depends on A (format + skeleton), parallel with B.
- **D. Search worker.** Scan worker, renderer-aligned extraction
  (worker-importable check), match table, find-band integration. Depends on C.
- **E. Downstream surfaces.** Scout + Scout viewer read support; verification
  pass over the tooling matrix. Depends on B.

**Phase 2 (opt-in write):**

- **F. Recorder write path.** Chunked writer + seal path (local accumulator,
  start-stub, multipart upload), monolith finalize-time policy, writer knobs
  (chunk policy, notables cap, monolith threshold; CI pins 0).
- **G. Live path.** Segment chunk members + supersede-tail, manifest chunk
  directory, local SQLite synthesis, live skeleton/stats re-emission, viewer
  live byte source + seal swap, live search. **Re-validates every ⚠️
  PROVISIONAL section first.**
- **H. Crash recovery rework.** Resolve the deferred mechanism
  (seal-against-surviving-buffer candidate) and implement.

**Phase 3 (default flip):**

- **I. Flip + retirement.** Default-on-write; retire `sampleStream`/four-cursor
  protocol for new logs, converge the forked list-model layer, message-copy
  revisit if the converter goes public.

## Deferred open issues

Recorded here so they aren't lost; each is out of this effort's scope:

1. **Score-edit / `invalidate_samples` representation on chunked format** —
   mid-sequence `ScoreEditEvent` insertion collides with index-identity
   chunks. Candidates surfaced: shell-only edits, append-at-end with span
   linkage, tail-chunk rewrite. Until resolved: today's whole-rewrite path,
   degraded with warning.
2. **Reused-sample carry-over in eval-set/retry** — candidate: raw zip-member
   byte-copy of the sample's prefix.
3. **Remote tag/metadata edit cost** — candidates: raw member copy without
   recompression, S3 `UploadPartCopy` prefix copy.
4. **Crash-recovery mechanism for chunked logs** (phase-2 effort H).
5. **Opt-in write mechanism** (env var vs CLI/eval option) — phase 2.
6. **Version-field gating** — the JJ follow-up.
7. **Default chunk-policy tuning** (count vs byte-target within the 1–8 MiB
   envelope) — settled by measurement during implementation.
8. **Per-sample manifest sharding** — only if per-run live-manifest growth
   (chunk-directory entries × concurrent samples) ever bites.

---

# Appendix A — Access-pattern inventory

Every completed-log access pattern and its landing (carried from the framing
doc, updated to the ratified decisions):

| # | Pattern | Accessed by | Landing |
|---|---|---|---|
| 1 | Header / summaries / listing | log list + sample list UI | unchanged (separate small entries) |
| 2 | Sample shell (metadata, scores, usage, error) | sample detail open; Python `exclude_fields` | `sample.json` — cheap by construction |
| 3 | Page messages by index window | Messages tab virtual list | index→chunk via start-named entries |
| 4 | Page events by index window | Transcript scroll | same |
| 5 | Tail / jump-to-last / follow | auto-follow, open-at-end | last chunk from `shell.sequences` |
| 6 | Structure without content (tree, outline, timeline) | first render of Transcript tab | `skeleton.json` |
| 7 | Deep links (event uuid, message→event) | URL deep links / citations | identity = sequence index; legacy uuid via one-time chunk scan |
| 8 | Event-type filtering | Transcript filter menu | stats-sidecar pushdown; exact digits / approximate pixels |
| 9 | In-sample search | find band | progressive scan worker |
| 10 | Full hydration / export / Python full read | JSON tab, downloads, `read_eval_log` | read all chunks + reassemble (explicit bulk op, warned) |
| 11 | Live streaming | running-sample view | ⚠️ manifest + segment chunks (provisional) |
| 12 | Python selective reads | analysis/scoring pipelines, scout | sample reader primitives |

# Appendix B — Transformation audit

Where every viewer transformation runs against skeleton + windowed fetches
(verified against viewer code at charting):

| Transformation | Reads | New home |
|---|---|---|
| `processPendingEvents` | `pending`, `uuid` | dropped — live-path only; at-rest logs contain no pending events |
| `collapseSampleInit` | event type | window-local; legacy no-span logs only |
| `groupSandboxEvents` | event type, timestamp | window-local (runs are contiguous; margin covers edges) |
| `injectScorersSpan` | span type | skeleton (synthesized wrapper over scorer spans) |
| `treeifyWithSpans` | `span_id`, `parent_id` | window-local — fetched bodies carry `span_id`; skeleton provides scaffolding |
| `transformTree` unwraps (`main`, `solvers`, `checkpoint`, same-name collapse) | span type/name | skeleton |
| `transformTree` child-shape matches (`unwrap_tools`, `unwrap_subtasks`, …) | direct-child event types + counts | skeleton `children` counts for outline; full fidelity window-local |
| `correctRetryTimestamps` / `groupRetryAttempts` | model error/success, `span_id`, timestamp | window-local with margin (retry runs adjacent) |
| `collapseFilters` default-collapse | span/step name+type, tool `agent`/`failed` | skeleton for spans; tool/subtask rows from fetched bodies |
| `filterEmpty` | children counts | skeleton counters |
| `removeNodeVisitor` family | event type, span name/type | outline: implicit; transcript: window-local |
| `makeTurns` / `collapseTurns` | event type sequence, depth | skeleton `gap_models` |
| `collapseScoring` | event type == score | skeleton notables |
| `computeTurnMap` | model-event positions | skeleton cumulative model counters |
| `pairToolApprovals` | approval `call.id` ↔ tool `id` | window-local with margin (pairs adjacent) |
| `flatTree` row math | tree + collapse state | skeleton descendant counts + extents |

# Appendix C — Decision record

| Section | Ticket | Resolved |
|---|---|---|
| Prior-art research | [#2](https://github.com/epatey/inspect_ai/issues/2) ([findings](https://github.com/epatey/inspect_ai/blob/research/prior-art-large-trace-viewers/design/research/prior-art-large-trace-viewers.md)) | 2026-07-18 |
| Zip/compression mechanics | [#3](https://github.com/epatey/inspect_ai/issues/3) ([findings](https://github.com/epatey/inspect_ai/blob/research/zip-chunked-log-mechanics/design/zip-chunked-log-mechanics.md)) | 2026-07-18 |
| Chunked on-disk layout | [#4](https://github.com/epatey/inspect_ai/issues/4) | 2026-07-18 |
| Structural skeleton | [#5](https://github.com/epatey/inspect_ai/issues/5) | 2026-07-18 |
| Attachments & pools | [#6](https://github.com/epatey/inspect_ai/issues/6) | 2026-07-18 |
| Live-view unification | [#7](https://github.com/epatey/inspect_ai/issues/7) | 2026-07-18 ⚠️ |
| Render prototype | [#8](https://github.com/epatey/inspect_ai/issues/8) ([FINDINGS](https://github.com/epatey/inspect_ai/blob/proto/eval2-render/prototypes/eval2-render/FINDINGS.md)) | 2026-07-18 |
| Viewer data loading | [#9](https://github.com/epatey/inspect_ai/issues/9) | 2026-07-18 (live source ⚠️) |
| Search | [#10](https://github.com/epatey/inspect_ai/issues/10) | 2026-07-18 |
| Python primitives & back-compat | [#12](https://github.com/epatey/inspect_ai/issues/12) | 2026-07-18 |
| Old-format degradation | [#13](https://github.com/epatey/inspect_ai/issues/13) | 2026-07-18 |
| Downstream tooling matrix | [#14](https://github.com/epatey/inspect_ai/issues/14) | 2026-07-18 |
| State/store reconstruction | [#16](https://github.com/epatey/inspect_ai/issues/16) | 2026-07-18 |
| Monolith threshold | [#17](https://github.com/epatey/inspect_ai/issues/17) | 2026-07-18 |
| Phasing & compat | [#18](https://github.com/epatey/inspect_ai/issues/18) | 2026-07-18 |
| Live skeleton/stats | [#19](https://github.com/epatey/inspect_ai/issues/19) | 2026-07-18 ⚠️ |

(#11 was absorbed into #5; #15 assembled this spec.)
