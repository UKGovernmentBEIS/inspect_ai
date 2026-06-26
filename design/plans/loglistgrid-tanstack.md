# LogListGrid: AG Grid → TanStack Table

## Context

The inspect viewer's collection views (tasks, folder/logs, sample) render with AG Grid. We're migrating them to TanStack Table — the engine `inspect_scout`'s transcripts panel already uses (`apps/scout/.../components/dataGrid/DataGrid.tsx`). Goals/constraints:

- **Behind an API abstraction.** Sort/filter run through a `getTranscripts`-shaped boundary (`filter`/`orderBy`/`pagination`) so the eventual move to server-side is a `queryFn` swap. Implemented **client-side** for now (evaluator over loaded rows); the streaming `ReplicationService`/IndexedDB sync itself is unchanged.
- **Async content in react-query.** The log handles/previews/details live in the react-query cache (fed by the sync), not zustand — table *state* (sorting, visibility) stays in zustand. See `loglist-content-react-query.md`.
- **Inspect-local now, shared later.** Build the TanStack grid inside `apps/inspect`. A shared monorepo grid is the eventual target but is deliberately premature until inspect's filtering/sorting model is settled — sharing now risks baking in the wrong abstraction.
- **Phased, not all-at-once.** Stand up a basic, correct table first; layer features back in over subsequent phases.
- **One component first.** This effort converts **`LogListGrid`** (serves `tasks` + `logs`/folder modes). `SamplesGrid` (sample view, with rotated headers / variable row heights / follow-output) is a separate effort after.

Scout's `DataGrid` is the structural analog, **not** a drop-in: it's wired to scout's *server* datapath (`manualSorting: true` with server fetch; column filters emit a `SimpleCondition` query DSL) and lives in `apps/scout` with scout-only imports. Inspect sorts/filters loaded rows client-side, so we borrow scout's *structure* (virtualizer, header/cell rendering, resize, keyboard nav) and reimplement sort client-side.

## Definitions: the IndexedDB stores

The viewer caches the log directory's contents in a per-directory Dexie/IndexedDB database (`AppDatabase`, `src/client/database/schema.ts`) across three object stores: **handles** (`logs`), **previews** (`log_previews`), and **details** (`log_details`). They form a handle → preview → details tier: the handle is the cheap identity/pointer for every file, the preview is the lightweight per-log summary the list needs to render a row, and the details blob is the full per-log header plus sample summaries. Tiering keeps the initial listing cheap and defers the heavy per-log payloads, which the `ReplicationService` (`src/state/sync/replicationService.ts`) fetches and writes in the background on separate work queues. All three are keyed by `file_path` (the log's `name`), and clearing/invalidating a file drops its row from all three (`clearCacheForFile`, `service.ts:399`).

### handles (`logs`)

| Aspect | Detail |
|---|---|
| Grain / key | One row per log file. Auto-increment `++id` primary key (preserves insertion order); `file_path` is the unique business key. Schema `logs: "++id, &file_path, mtime, task, task_id, cached_at"` (`schema.ts:93`). |
| Contents | Tiny pointer record (`LogHandleRecord`, `schema.ts:6`): `file_path`, `file_name`, `task`, `task_id`, `mtime`, `cached_at`. Mirrors the server `LogHandle` (`name`/`task`/`task_id`/`mtime`). No log payload. |
| Populated by | `ReplicationService.sync()` → `DatabaseService.writeLogs()` (`service.ts:74`) from `api.get_logs(mtime, count)`; `mtime` drives incremental sync and the default newest-first sort (`readLogs`, `service.ts:98`). |
| Consumers | Drives the row set. `setLogHandles` → react-query `LogsContent.handles` (`logsContent.ts:33`); read via `useLogHandles` in `LogViewLayout.tsx:35`, `useLoadLog.ts:21`, and `hooks.ts` (e.g. `:530`). |

### previews (`log_previews`)

| Aspect | Detail |
|---|---|
| Grain / key | One row per log file. Primary key `file_path`. Schema `log_previews: "file_path, preview.status, preview.task_id, preview.model, cached_at"` (`schema.ts:96`) — indexes the common list-query/filter fields. |
| Contents | `LogPreviewRecord` (`schema.ts:18`) wrapping a `LogPreview` (`api/types.ts:413`): `eval_id`/`run_id`, `task`/`task_id`/`task_version`, `status`, `error`, `model`/`model_roles`, `started_at`/`completed_at`, `primary_metric`. A lightweight summary — no samples. |
| Populated by | `_previewQueue` (concurrency 2, batched 24) calls `api.get_log_summaries()` and flushes via `writeLogPreviews()` (`service.ts:136`). Missing/`"started"` previews are re-queued on each sync (`queueMissingOrStartedPreviews`). |
| Consumers | The list grid's row data. `mergeLogPreviews` → `LogsContent.previews`; read via `useLogPreviews` in `LogsPanel.tsx:71` and `SamplesPanel.tsx:131`, and via `useLogsContent` in `hooks.ts:780`. |

### details (`log_details`)

| Aspect | Detail |
|---|---|
| Grain / key | One row per log file. Primary key `file_path`. Schema `log_details: "file_path, details.status, cached_at"` (`schema.ts:100`). |
| Contents | `LogDetailsRecord` (`schema.ts:30`) wrapping a `LogDetails` (`api/types.ts:68`): full header (`eval`, `plan`, `results`, `stats`, `error`, `tags`, `metadata`, `version`) **plus** `sampleSummaries: SampleSummary[]` and the S3 `etag`. The heavy blob — grows with sample count. |
| Populated by | `_detailQueue` (concurrency 24, batch 1) calls `api.get_log_details()` per file and flushes via `writeLogDetails()` (`service.ts:218`); `findMissingDetails` (`service.ts:275`) drives backfill. |
| Consumers | Per-log content + sample summaries. `mergeLogDetails` → `LogsContent.details`; read via `useLogDetails` in `LogListGrid.tsx:195` (score/metric columns), `columns/hooks.tsx:107`, and `SamplesPanel.tsx:113` (samples views). |

### "Summary" terminology

The word *summary* shows up at two grains, which map onto these stores as follows:

- **Log summary** — the `api.get_log_summaries()` response, typed `LogPreview` (`api/types.ts:217`, `:413`). This *is* the **previews** store's payload: the API call says "summary" while the cached record is named `preview`, but they're the same lightweight per-log object. So "log summary" ≡ a `previews` row.
- **Sample summary** — a `SampleSummary` (`api/types.ts:129`), one per sample (id/epoch/score/error/limit/tokens…). A finer grain that lives **inside the details store** as `LogDetails.sampleSummaries` (`api/types.ts:79`), fetched by `get_log_details()` — it is *not* in `previews`. The log list reads these (through `details`) to derive per-task aggregates (sample count, error/limit columns); the samples views render one row per sample summary.

## Feature roadmap (nothing is dropped)

Every current `LogListGrid` feature must survive the migration. Phase 1 deliberately ships the minimum to render content correctly; everything else is sequenced into later phases, not abandoned.

| Feature | Phase |
|---|---|
| Virtualized rows, sticky header, all columns with correct cell renderers / accessors / formatters / tooltips | **1** |
| Mode-specific column set + ordering (tasks vs logs) | **1** |
| Dynamic score-column discovery (`score_<scorer>/<metric>`, `metric_<name>`) | **1** |
| Column visibility: default-hidden sets + Columns popover + per-scorer ↔ by-metric toggle | **1** |
| Row selection highlight + click-to-navigate + Cmd/Shift/middle-click → new tab | **1** ✅ |
| Shared query types/builders (`Condition`/`OrderBy`/`Pagination`) via codegen → `@tsmono/inspect-common` | **2** ✅ |
| Async content (handles/previews/details) in the react-query cache, out of zustand | **2** ✅ |
| Client-side sorting incl. folder-pinned + NaN-aware/date comparators, sort indicators, per-`scopeKey` persistence | **2** ✅ |
| Per-column filter UI (text/number/date popovers → `Condition`) + Reset Filters + filtered-count | **3** ✅ |
| Keyboard navigation (arrows / Home / End / PgUp-Dn / Enter), scroll-into-view | **4** ✅ |
| Ctrl+F find band (`FindBandUI`) | **5** |
| Column resizing | **6** |
| Auto-fit-to-grid-width (`autoSizeStrategy: fitGridWidth`) + user-resize-override suppression | **6** |
| Column resizing + per-scope width persistence | **6** |
| Column reordering (header drag) | deferred |
| Column pinning (`type` icon col pinned-left) | deferred |
| Multi-line/preformatted cell tooltips (model-roles, task-args JSON — was `PreformattedTooltip`, now native `title`) | deferred — accept native-`title` for now |
| Infinite scroll / true pagination (cursor shape exists; client fetches all) | separate (server-side) |

Phase numbers past 1 are a planning order, not a contract; we can resequence as we learn. The point is the full set lands eventually.

## Phase 1 — Stand up the table (render + navigate) — ✅ DONE

> Committed on branch `loglist-tanstack-phase1` (ts-mono `b48e211`, rebased on `origin/main`; parent repo bumps the submodule pointer). See **Phase 1 outcome** below for what shipped and what diverged from this sketch.

Deliver an inspect-local TanStack grid that renders the logs and tasks views with correct content and lets the user click into a log. No sorting, persistence, find, keyboard nav, resizing, or filtering yet.

**New inspect-local grid** under `apps/inspect/src/app/shared/data-grid/`:

- **`DataGrid.tsx`** — generic `<TRow>` TanStack wrapper. `useReactTable` with `getCoreRowModel`, `columnVisibility` state, `@tanstack/react-virtual` for rows. Renders header + cells via `flexRender`. Fixed column widths from each column's `size`; horizontal scroll when total width exceeds the container (like scout). Row selection highlight + click handler: normal click navigates, Cmd/Ctrl/Shift/middle-click open in new tab. (No sort/resizer/keyboard wiring yet — those land in later phases; leave clean seams for them.)
- **`DataGrid.module.css`** — adapt scout's CSS module (drop drag/reorder/resizer classes for now). Reuse existing `shared/gridCells.module.css` for cell-content classes (`iconCell`, `numberCell`, `taskText`, `scoreCell`, …) referenced by cell renderers.
- **`columnTypes.ts`** — local `ExtendedColumnDef<TRow>`: `ColumnDef<TRow>` + `meta` (`align`, `sortComparator`), `headerTitle`, `titleValue`, `textValue`. (`size`/`minSize`/`maxSize` come from TanStack's own `ColumnDef`. `meta.sortComparator` is declared but unpopulated until phase 2; `textValue` unpopulated until phase 4; filter fields later.)

**Column porting** — translate `useLogListColumns` (`log-list/grid/columns/hooks.tsx`) from AG `ColDef<LogListRow>[]` to `ExtendedColumnDef<LogListRow>[]`:

- `field`/`colId` → column **`id`** set to the *same field key* (`type`, `task`, `score`, `score_<scorer>/<metric>`, `metric_<name>`, …) so the existing `columnVisibility` record and the Columns popover keep working unchanged.
- `valueGetter` → `accessorFn`; `cellRenderer`(`params.data`/`params.value`) → `cell: ({ row, getValue })`; `valueFormatter` folded into `cell`. `tooltipValueGetter` → `titleValue: (row) => string | undefined`, rendered by the DataGrid as the cell `title`. `initialWidth`→`size`, `min/maxWidth`→`minSize`/`maxSize`. Every column uses `accessorFn` + explicit `id` (not `accessorKey`) so score-column ids containing `/` or `.` aren't misread as deep key paths.
- **Comparators are NOT carried in phase 1.** The existing AG comparators read `IRowNode.data`, a shape that won't match phase 2's row-based local sort; carrying them would be porting-the-wrong-way. Phase 2 reconstructs comparators in this same hook (it has `scorerMap` for value types).
- Mode-specific ordering/visibility logic (tasks vs logs, default-hidden sets, score-mode matching) stays as-is.
- `pickerColumns`: emit a lightweight `ColDef`-shaped list (`{ colId, headerName }[]`) so the shared `ColumnSelectorPopover` (still used by the AG-Grid samples view) is untouched.

**Column visibility** — map the existing `visibility` record (keyed by field) to TanStack's native `VisibilityState` (keyed by the matching column `id`). Columns popover and per-scorer/by-metric toggle keep working via the existing store-backed `columnVisibility`.

**LogsPanel integration** (`log-list/LogsPanel.tsx`) — every `gridRef.api` use is filter-only (`getFilterModel`/`setFilterModel`, ~lines 327–377), so for phase 1:

- Drop the `gridRef` prop to `LogListGrid` and the AG `gridRef`.
- Reduce `handleColumnVisibilityChange` to just `setColumnVisibility(merged)`.
- Remove the Reset Filters button + `hasFilter`/`filteredFields` (or pass `[]`); footer `filteredCount` = item count (no filtering yet). These return when filtering does.

**Dependencies** — add to `apps/inspect/package.json`: `@tanstack/react-table@^8.21.3`, `@tanstack/react-virtual@^3.14.3` (same versions as scout); `pnpm install` in `ts-mono`.

**Phase 1 files**
- *Create*: `apps/inspect/src/app/shared/data-grid/{DataGrid.tsx,DataGrid.module.css,columnTypes.ts}`.
- *Modify*: `log-list/grid/LogListGrid.tsx` (rewrite on DataGrid, no sort/find/keyboard yet), `log-list/grid/columns/hooks.tsx` (emit TanStack columns + picker shims), `log-list/LogsPanel.tsx` (drop gridRef/filter wiring).
- *Untouched*: `ColumnSelectorPopover`, `FindBandUI`, `gridComparators.ts`, `SamplesGrid` + samples views, all data/loading code, the AG `gridStateByScope` store slice (left in place until phase 2 replaces it).

**Phase 1 verification**
- `pnpm typecheck`, `pnpm lint`, `pnpm format:check`, `pnpm test` in `ts-mono`.
- `pnpm dev` against a logs dir with multiple folders + tasks. Confirm: logs/folder view renders all rows with correct cell content (task, model, score, status, completed, scores…); tasks view renders without the type column and in tasks order; default-hidden columns are hidden; Columns popover toggles base + score columns; per-scorer ↔ by-metric switch; row click navigates; Cmd/Shift/middle-click open new tab; virtualization smooth on a large dir.

## Phase 1 outcome & findings

**Verified:** `tsc --noEmit`, eslint, prettier all clean; 477/477 unit tests pass; `top-level-views.spec.ts` e2e 8/8 pass (renders Tasks/Folders/Samples, click-navigation, folder grouping, ARIA selectors) against msw-mocked data. `pnpm dev` visual pass not separately run — the e2e exercises the same render/navigate paths.

**Decisions / divergences from the sketch:**
- **ARIA roles as the stable selector.** The DataGrid sets `role="grid"/"rowgroup"/"row"/"columnheader"/"gridcell"` (CSS-module class names are hashed and unusable as selectors). e2e selectors target these roles.
- **DataGrid click contract simplified.** `onRowActivate(row)` fires only on a plain left click; modifier/middle clicks are left to the task cell's native `<a href>` overlay (matches prior AG behavior — new-tab only works from the task cell). Row selection highlight is internal state seeded from an optional `selectedRowId`.
- **Tooltips degrade to native `title`.** The AG `PreformattedTooltip` (multi-line model-roles / task-args JSON) is dropped; `titleValue` feeds the native `title` attribute. Revisit if multi-line fidelity matters.
- **Row/header heights:** row 30px, header 25px; fixed widths + horizontal scroll (auto-fit-to-width deferred).
- **Lint suppression:** `react-hooks/incompatible-library` on `useReactTable` — the same documented suppression scout's DataGrid uses (React Compiler can't memoize TanStack's returned fns).
- **filteredCount** is set to `data.length` (no filtering yet) so the footer count stays accurate.

**Rebase finding (origin/main):** PR #365 enabled `noUncheckedIndexedAccess` for `apps/inspect`. New code had to narrow indexed access — done via `Object.entries(scorerMap)` for the per-scorer map and guards on `roles[0]` / `contributors[0]` / `splice` results (proper narrowing, not `@ts-expect-error`). The conflicts the rebase surfaced in `LogListGrid.tsx`/`hooks.tsx` were only #365's suppressions on the AG code this rewrite deletes — nothing substantive lost.

**Carried over (left in place, addressed later):**
- Old AG grid-state store slice (`gridStateByScope` / `setLogsGridState` in `state/types.ts` + `logsSlice.ts` + `useLogsListing`) is now unused by the log list — phase 2 replaces it.
- `ag-grid-community`/`ag-grid-react` deps remain (still used by the samples views).
- e2e: `log-list-filters.spec.ts` is `describe.skip`'d (AG-api/sort/filter); `top-level-views.spec.ts` repointed to ARIA roles.

**Env note:** the rebase bumped Playwright; running e2e needed `pnpm exec playwright install chromium` (local cache only).

## Phase 2 — Sorting behind the API + content in react-query — ✅ DONE

Full detail in `loglist-content-react-query.md`. Summary of what shipped:

- **Query DSL via codegen.** Scout's Pydantic query models (`Condition`/`Operator`/`LogicalOperator`/`OrderBy`/`Pagination`) copied into inspect (`src/inspect_ai/_view/_query/`) and emitted into `inspect-openapi.json` via `RootModel` stub endpoints, so they codegen into `@tsmono/inspect-common`. `ConditionBuilder`/`Column` builders ported into `@tsmono/inspect-common/query`.
- **Client-side listing query (transitional).** `apps/inspect/.../log-list/listing/`: `evaluateCondition` + `compareByOrderBy` + `paginate` → `applyListingQuery`, exposed via the `useLogsListingQuery` hook (a `useMemo` over reactive rows — becomes a server `useQuery` when filter/sort move server-side). Column `meta.sortComparator` + `getValue`/`getComparator` accessors come from `useLogListColumns`.
- **Content out of zustand.** `state/queryClient.ts` singleton + `state/logsContent.ts` cache (`useLogsContent`); the sync writes via `setQueryData` (logsSlice content actions are thin shims); all consumers migrated.
- **Sorting wired.** DataGrid gained clickable sort headers (multi-sort), asc/desc carets (`aria-hidden`), `manualSorting` + controlled `sorting`/`onSortingChange`. `LogListGrid` splits folders/files, sorts files via `useLogsListingQuery` (folders pinned on top — replaces the folder-first comparator), persists sort per scope in `gridStateByScope` (now holds `LogListGridState { sorting }` instead of AG `GridState`).

**Phase 2 outcome & findings:**
- **Folder-first comparator dropped.** Folders are derived/pinned in the panel (split before the query), not via a direction-aware comparator.
- **`gridStateByScope` kept its name** (holds TanStack sorting now); only the value type changed AG `GridState` → `LogListGridState`. Avoided a cosmetic grid→table rename.
- **e2e:** added a `Sorting` test in `top-level-views.spec.ts` (clicks the Task header, asserts asc/desc order) driving ARIA roles; sort carets are `aria-hidden` so the glyph doesn't leak into the header's accessible name. `log-list-filters.spec.ts` stays `describe.skip` until the filter UI lands.
- **Verified:** typecheck/lint/format clean; 489 unit tests; 9/9 `top-level-views` e2e.

## Phase 3 — Per-column filter UI — ✅ DONE

Full detail in `loglist-filtering.md`. Summary of what shipped:

- **Shared `columnFilter/` module.** Scout's column-filter editor (funnel button → per-type popover → `SimpleCondition`) ported into `@tsmono/inspect-components/columnFilter` (operators, parse/build, popover, per-type inputs). DataGrid stays inspect-local and consumes the shared control.
- **Hover-reveal affordance.** The funnel is hidden until the header is hovered and stays lit when that column is actively filtered (origin/main's behavior, via inspect DataGrid header CSS — not scout's always-visible button).
- **Type-aware evaluator.** `evaluateCondition` coerces both operands by the column's `filterType` (number/duration → `Number`; `date` → day-truncated epoch; `datetime` → epoch; boolean; string) so `<`/`=`/`BETWEEN`/`IN` are correct for numbers and dates. `getFilterType` threads through `applyListingQuery`/`useLogsListingQuery`.
- **Per-scope persistence + chrome.** `LogListGridState` gained `columnFilters`; `combineFilters` AND-combines them into one `Condition`; the Reset Filters navbar button + Columns-popover filtered-field flagging + hide-clears-filter are restored.

## Phase 4 — Keyboard navigation — ✅ DONE

Restored the arrow-key navigation origin/main had (its AG `LogListGrid` wired `createGridKeyboardHandler`; phase 1 dropped it). Notably main had **no test coverage** for this — the port ships the unit + e2e it lacked.

- **Pure resolver.** `shared/data-grid/keyboardNav.ts`: `resolveKeyboardNavTarget({key, metaKey, ctrlKey, currentIndex, rowCount, pageJump}) → number | null`, matching the prior AG semantics — ↑/↓ ±1 (clamped), Cmd/Ctrl+↑/↓ jump to first/last, Home/End, PageUp/Dn ±10, from an empty selection any nav key lands on row 0, `null` for non-nav keys or an empty grid. Unit-tested in `keyboardNav.test.ts`.
- **DataGrid wiring.** The `role="grid"` container is `tabIndex={0}` with an `onKeyDown` that applies the resolver to the internal `selectedId` (select target + `rowVirtualizer.scrollToIndex(target, {align:"center"})`), and Enter/Space activates the selected row. A focus guard ignores keys while an `input`/`textarea`/`select` is focused (so typing in a filter popover doesn't move the selection); a plain row click pulls focus to the grid so the keyboard works after a click.
- **e2e:** `Keyboard navigation` describe in `top-level-views.spec.ts` — focus the grid, ↓/↓/↑ move `aria-selected`, Enter navigates under `/tasks/`.
- **Verified:** typecheck/lint/format clean; resolver units + full `top-level-views` e2e (12) green.

## Where we are & the path to a good point

**Done (phases 1–4).** The log list renders every column across tasks/folder modes, navigates on click *and keyboard*, sorts (multi-sort, folder-pinned, persisted), filters (per-column popovers + Reset Filters + filtered-count), toggles column visibility (Columns popover + score-mode switch), and persists sort+filters per scope — all served from the react-query content cache, off the old zustand content path. What remains is parity polish and getting the log list fully off AG Grid.

**Bar for "a pretty good point":** parity with origin/main's AG log list on what users actually feel, with the log list no longer depending on `ag-grid-*`. Two phases remain, in this order:

- **Phase 5 — Ctrl+F find.** Port `FindBandUI` + a per-row search string built from visible columns' `textValue`/accessor (replacing AG's `getCellValue` cache); scroll-to-match + select. A real regression vs origin/main if left out. (Reuses the scroll-into-view established in phase 4.)
- **Phase 6 — Layout fit.** Auto-fit-to-grid-width (`autoSizeStrategy: fitGridWidth` analog) so columns fill the grid — the most visible "unfinished" gap today, since we currently render fixed widths + horizontal scroll — plus user drag-resize (`enableColumnResizing` + resizer UI) with resize-override suppression, persisting widths per scope alongside sort/filters. Done together because resize overrides auto-fit.

After phase 6 the log-list migration is at a solid, shippable point and `ag-grid-*` is used only by the samples views.

**Definition of done (before calling it "good").** A parity sweep against origin/main — visual + behavioral — to catch silent drops: default column widths, tooltip content, empty/loading states, persistence across scope switches, new-tab behavior. Run `pnpm dev` on a large multi-folder logs dir, plus the full e2e + unit suites.

## Deliberately deferred (not needed for a good point)

- **TODO: use `skipToken` for the logs-content query before a directory is known.** `state/logsContent.ts:24` keys the content query on `["logs-content", logDir ?? ""]`, so before `logDir` hydrates it runs/caches under an empty-string key (`["logs-content", ""]`). Switch to react-query's `skipToken` (disable the query until `logDir` is set) — the standard pattern scout uses (e.g. `apps/scout/.../TranscriptsPanel.tsx`).
- **TODO: verify multi-column sort mechanics vs origin/main.** Our DataGrid runs TanStack `enableMultiSort: true` with the library defaults (Shift/Ctrl-click = additive multi-sort; plain click replaces). Confirm this matches AG's behavior on main — specifically what a **plain click on a second column header does when another column is already sorted** (replace the sort vs add to a multi-sort), and the modifier for additive sort. If it diverges, fix it and add an e2e; if it matches, capture an e2e to lock it in.
- **Column reordering** (header drag) and **column pinning** (`type` icon col pinned-left) — low-use AG niceties.
- **Multi-line/preformatted tooltips** — accept the native-`title` drop (model-roles / task-args JSON); restore a custom tooltip only if requested.
- **New-tab parity** beyond the task cell's `<a>` overlay (a row-level Cmd/middle-click handler would generalize it).
- **Per-column filter clear affordance** and **filter autocomplete suggestions** (the latter needs an inspect API for per-column distinct values) — see `loglist-filtering.md`.
- **ARIA-label audit vs origin/main** — reconcile the DataGrid's roles/labels (the funnel `aria-label="Filter <columnId>"` substring-collides with header/segment names) so accessibility/automation don't regress.

## Separate efforts (out of this migration's scope)

- **`SamplesGrid` migration** — cross-log `SamplesPanel` + single-log `SampleList`, with rotated headers, follow-output, and multiline rows. Its rows are already client-computed (cross-log even reads the same react-query content cache), so there's no datapath work; the cost is DataGrid feature delta (keyboard nav from phase 4 carries over). Completing it removes the last `ag-grid-*` usage and `ColumnSelectorPopover`'s AG coupling.
- **Server-side filter/sort + infinite scroll** — the payoff of the API boundary: replace `useLogsListingQuery`'s client `useMemo` (and the content-cache population) with a server `getLogsListing(dir, filter, orderBy, pagination)` query, deleting the transitional `log-list/listing/` evaluator. `Pagination` is cursor-shaped already.
- **Scout reconciliation (user-owned)** — point scout at `@tsmono/inspect-common/query` + the shared `columnFilter/` module and collapse the duplicated query models to a single Python codegen source.
