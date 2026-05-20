# Viewer Log Editing

## Summary

Add the ability to edit eval log files from inside the inspect viewer. The viewer
currently is read-only against `EvalLog` files; this work expands the view server
with HTTP endpoints that wrap the existing Python edit APIs in
`inspect_ai.log` and lays groundwork for matching UI affordances.

Scope is everything in the inspect API whose edit payload carries
`ProvenanceData` (either as a direct argument or nested in the edit value):

| Python API | Wrapped server endpoint (planned) | Phase |
|------------|-----------------------------------|-------|
| `edit_eval_log` (`TagsEdit`)      | `POST /api/log-edit/{log}` | 1 (this change) |
| `edit_eval_log` (`MetadataEdit`)  | `POST /api/log-edit/{log}` | 1 (this change) |
| `invalidate_samples`              | `POST /api/log-invalidate-samples/{log}` | 2 |
| `uninvalidate_samples`            | `POST /api/log-uninvalidate-samples/{log}` | 2 |
| `edit_score`                      | `POST /api/log-edit-score/{log}` | 3 |

`uninvalidate_samples` does not take `ProvenanceData` but pairs with
`invalidate_samples` and belongs alongside it. `edit_score` takes a
`ScoreEdit` rather than a separate `ProvenanceData`, but `ScoreEdit` has
`provenance: ProvenanceData | None` nested inside it — so the operation
fits the same "authored, attributable mutation" pattern as the others.

## Motivation

Eval log mutation has, until now, been a Python-only workflow:

```python
log = read_eval_log(path)
log = edit_eval_log(log, [TagsEdit(tags_add=["qa_passed"])], ProvenanceData(author="alice"))
write_eval_log(log)
```

Surfacing the same operations through the viewer lets reviewers, QA, and
non-Python users perform the same workflows without dropping into a shell or
notebook. The natural delivery vehicle is the existing view server (both the
aiohttp and FastAPI variants) so that hosted viewer deployments (e.g.
inspect-flow) inherit the new endpoints for free.

## Non-goals

- CLI commands for editing logs (already noted as out-of-scope in
  `log_edits_tags_metadata.md`; tracked separately).
- Concurrency control for local-filesystem logs. S3 conditional writes are
  wired up in Phase 1 (see below); local-file ETag synthesis is deferred — the
  single-user `inspect view` case is the dominant local one and last-writer-wins
  is acceptable there.

## Phase 1 — Tag + metadata edits (this change)

### Endpoint

```
POST /api/log-edit/{log}
Content-Type: application/json

{
  "edits": [
    { "type": "tags",     "tags_add": ["qa_passed"], "tags_remove": ["needs_qa"] },
    { "type": "metadata", "metadata_set": {"reviewer": "alice"}, "metadata_remove": ["draft_notes"] }
  ],
  "provenance": { "author": "alice", "reason": "QA complete" }
}
```

The request body matches the existing `LogUpdate` pydantic model
(`inspect_ai.log._edit.LogUpdate`): a discriminated union of `TagsEdit` /
`MetadataEdit` plus a `ProvenanceData`. Both branches share a single endpoint
because they share an implementation — `edit_eval_log` applies each edit in
order, accumulating into the same `LogUpdate` entry on `log.log_updates`.

Response: the updated `EvalLog` header (same shape as `GET /api/logs/{log}?header-only=0`).
This gives the client the recomputed `tags` / `metadata` and the new
`log_updates` entry without a follow-up round trip.

### Handler shape

```python
log = await read_eval_log_async(file, header_only=True)
log = edit_eval_log(log, body.edits, body.provenance)
await write_eval_log_async(log, location=file, header_only=True)
```

`header_only=True` is correct on both sides: tags, metadata, and `log_updates`
all live in the header, and `write_eval_log_async(..., header_only=True)`
appends the new header to the existing zip without touching samples. This keeps
edits cheap for large logs.

### Access policy

`AccessPolicy` (FastAPI) gains `can_write` alongside the existing
`can_read` / `can_delete` / `can_list`. `OnlyDirAccessPolicy` returns `True` for
files inside the log dir (mirroring `can_delete`). aiohttp continues to rely on
the `validate_log_file_request` helper plus the optional `Authorization` header.

### Errors

| Condition | Response |
|-----------|----------|
| File outside `log_dir` (no auth) | 401 (aiohttp) / 403 (FastAPI) |
| Body validation fails (pydantic) | 422 |
| `edit_eval_log` raises `ValueError` (empty tag, overlap, etc.) | 400 |
| `If-Match` doesn't match current S3 ETag | 412 Precondition Failed |
| Underlying read/write fails | 500 |

### ETag / If-Match (S3 only)

S3-hosted logs already carry an ETag through `read_eval_log_async` and
`write_eval_log_async(..., if_match_etag=...)` does the conditional `PutObject`,
raising `WriteConflictError` on mismatch. Phase 1 plumbs both through the
viewer:

- `GET /api/logs/{log}` sets an `ETag` HTTP header when the recorder returns
  one (S3 today, nothing on local).
- `POST /api/log-edit/{log}` reads `If-Match` and forwards it to
  `apply_log_edits` → `write_eval_log_async`. On `WriteConflictError` the
  response is HTTP 412 Precondition Failed. The success response carries the
  new `ETag` so the client can chain conditional edits without a fresh `GET`.

`If-Match` is optional. Omitting it falls back to last-writer-wins, matching
the existing `write_eval_log(..., if_match_etag=None)` semantics. The viewer
UI should send `If-Match` whenever it has one — the server doesn't enforce
that policy.

Local-file ETag is deferred. There's no etag mechanism in the recorder for
local files today; synthesizing one (mtime+size, or a content hash) plus a
per-path lock would close the race window for a single-process viewer, but
the single-user case doesn't warrant the complexity yet. Listed as a
follow-up below.

### Metadata-specific behavior

`MetadataEdit` accepts two operations per edit:

- `metadata_set: dict[str, Any]` — keys to add or replace. Values may be any
  JSON value (including `null` — see edge case below).
- `metadata_remove: list[str]` — keys to delete.

The viewer's edit dialog serializes UI rows into a single `MetadataEdit`:
new + edited rows go into `metadata_set`, deleted rows go into
`metadata_remove`. Type intent for new rows is honored — picking `string`
saves `"43"` as the string `"43"`, picking `object` requires well-formed
JSON. Structural text (leading `{`, `[`, `"`) is always validated as JSON
regardless of the dropdown so a stray `{a: 1}` surfaces an error instead of
silently saving as a string.

One server-side gotcha that needed fixing: the no-op filter inside
`edit_eval_log` previously used `current_metadata.get(k) != v`, which
mis-classified "adding a new key whose value is `None`" as a no-op (because
`dict.get` returns `None` for absent keys). The filter now tests key
presence separately so null-valued additions land in `log.metadata`.

### Out of scope for Phase 1

- Local-file ETag synthesis.
- Surfacing edit history (the `log_updates` audit trail) in the viewer UI —
  appears in the JSON tab but no dedicated card yet.

## Phase 2 — Sample invalidation

Two endpoints, each wrapping the matching Python function:

```
POST /api/log-invalidate-samples/{log}
{
  "sample_uuids": ["..."] | "all",
  "provenance":   { "author": "...", ... }
}

POST /api/log-uninvalidate-samples/{log}
{
  "sample_uuids": ["..."] | "all"
}
```

These do touch sample records, so a full read + write (not header-only) is
required. We need to think about:

- Streaming large logs through memory (consider `read_eval_log_sample` style
  partial mutation) — open question.
- Whether the response should be the new header or the modified samples.

## Phase 3 — Score editing

Wraps `edit_score` from `inspect_ai.log._score`:

```
POST /api/log-edit-score/{log}
{
  "sample_id":  "<sample id>",
  "epoch":       1,                 // optional; required when multiple epochs share the id
  "score_name": "accuracy",
  "edit":        {                  // ScoreEdit
    "value":       0.8,             // or "UNCHANGED"
    "answer":      "yes",           // or "UNCHANGED" / null
    "explanation": "UNCHANGED",
    "metadata":    "UNCHANGED",
    "provenance":  { "author": "alice", "reason": "regrade after rubric update" }
  },
  "recompute_metrics": true
}
```

Notes specific to this phase:

- `ScoreEdit.provenance` is nested inside the edit payload (not a separate
  body field), matching the Python API. The viewer should always populate
  it — `None` is reserved for the original scorer-emitted score, and once
  edits append to `Score.history`, missing provenance becomes ambiguous.
- `edit_score` mutates in-place: it appends a `ScoreEditEvent` to the
  sample's event tree and pushes the prior `ScoreEdit` onto `score.history`.
  That means **full read + full write** — not header-only. Same memory
  implications as Phase 2.
- `recompute_metrics=True` (the Python default) re-aggregates the log's
  metrics so `EvalResults.scores` stays consistent with the edited sample
  scores. The server should preserve that default; a client that wants to
  defer metric recomputation can opt out.
- New `ValueError` paths surface as HTTP 400 (sample not found, ambiguous
  sample-id without epoch, creating a new score without a `value`).
- Auth: gated by `can_write` like the other edit endpoints.

## Phase 4 — View UI

Phase 1 already ships the basic UI affordances: the **PrimaryBar** header
renders tags as inline outline pills with an Edit affordance; the
**Task** tab repeats the chip row; the **Info** tab's metadata card has its
own Edit affordance opening a structured metadata editor (typed key
add/remove, autogrowing value textareas, change summary, provenance
fields). Remaining UI work:

- Expandable edit history card surfacing `log_updates` with provenance
  (analogous to the existing invalidation card).
- Tag filter on the log list view.
- Sample-level "invalidate" / "uninvalidate" affordances (Phase 2).
- Inline score editor on the sample view with score history + provenance
  surfaced from `score.history` (Phase 3).

A follow-up doc will cover the UI design once the server side is stable.

## Open questions

- Auth/identity: today the viewer has a single shared `Authorization` token. We
  surface `provenance.author` from the client. If we ever want server-attested
  authors, we need a real auth story — out of scope here.
- Editing in-progress logs: edits against a still-running eval would race
  the recorder. Phase 1 simply doesn't gate this; the recorder will overwrite.
  Worth deciding before Phase 2/3 (sample invalidation and score editing can
  plausibly target a running eval).
- Eval-format vs JSON-format logs: `header_only` write is implemented per
  recorder. Verify both recorders honor `header_only=True` semantics — Phase 1
  tests cover the `.eval` recorder; `.json` is a follow-up if we keep
  supporting it for editing.

## Files touched (Phase 1)

Server / API:

| File | Change |
|------|--------|
| `src/inspect_ai/_view/common.py` | shared `apply_log_edits` (read → `edit_eval_log` → write), ETag plumbing |
| `src/inspect_ai/_view/server.py` | aiohttp: `POST /api/log-edit/{log}`, `If-Match` → `WriteConflictError` → 412 |
| `src/inspect_ai/_view/fastapi_server.py` | FastAPI: `POST /log-edit/{log:path}`, `AccessPolicy.can_write`, `OnlyDirAccessPolicy.can_write` |
| `src/inspect_ai/_view/user_info.py` | new — `GET /api/user-info` returning the git alias (email local-part → user.name → OS login) so the viewer can prefill `provenance.author` |
| `src/inspect_ai/log/_edit.py` | fix: no-op filter for `MetadataEdit` tests key presence separately so null-valued additions aren't dropped |
| `tests/_view/test_view_server.py` | parameterized roundtrip + validation tests (tags + metadata, S3 ETag, null-value persistence) |
| `tests/log/test_edit.py` | `MetadataEdit` unit + write-then-read roundtrip tests |
| `tests/_view/test_user_info.py` | git-alias resolution order |

Viewer UI (Phase 1 client surface):

| File | Change |
|------|--------|
| `apps/inspect/src/client/api/view-server/api-view-server.ts` | `edit_log` POST + ETag capture; `get_user_info` |
| `apps/inspect/src/client/api/client-api.ts` | wraps `edit_log` (invalidates JSON + .eval read caches) and `get_user_info` |
| `apps/inspect/src/app/log-view/title-view/TagChip.tsx` + CSS | outline-only chip with truncation + `title` hover |
| `apps/inspect/src/app/log-view/title-view/TagStrip.tsx` | extracted chip strip; Edit pill flows as a sibling in the header so it stays beside wrapped chips |
| `apps/inspect/src/app/log-view/title-view/EditButton.tsx` + CSS | `link` / `pill` variants; both use body color |
| `apps/inspect/src/app/log-view/title-view/EditTagsDialog.tsx` | restyled shell; multi-line change summary; pre-fills `Author` from `get_user_info` |
| `apps/inspect/src/app/log-view/title-view/EditMetadataDialog.tsx` + CSS | new dialog: typed add-key, autogrowing textareas, change summary, JSON-syntax validation, scroll-to-new-row |
| `apps/inspect/src/app/log-view/title-view/AutogrowText.tsx` | ResizeObserver-driven height matching |
| `apps/inspect/src/app/log-view/title-view/{ChangeSummary,ProvenanceFields}.tsx` | shared dialog chrome |
| `apps/inspect/src/app/log-view/title-view/PrimaryBar.{tsx,module.css}` | tag rail in header; wrapper grid + shrink-priority rules |
| `apps/inspect/src/app/log-view/tabs/TaskTab.tsx` | tags chip row + inline Edit pill mirrors the header |
| `apps/inspect/src/app/plan/PlanCard.tsx` + CSS | Metadata card Edit affordance |
| `packages/inspect-components/src/content/MetaDataGrid.tsx` | fix: route `{_html: <jsx>}` values through `RenderedContent` (they were being dumped as nested rows) |
| `packages/react/src/components/{Card,Modal}` | CardHeader switched grid → flex so optional `children` (e.g. Edit) sit inline; Modal gained `footer` + `width` props |
