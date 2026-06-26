# LogListGrid: AG Grid → TanStack Table

## Context

The inspect viewer's collection views (tasks, folder/logs, sample) render with AG Grid. We're migrating them to TanStack Table — the engine `inspect_scout`'s transcripts panel already uses (`apps/scout/.../components/dataGrid/DataGrid.tsx`). Goals/constraints:

- **Behind an API abstraction.** Sort/filter run through a `getTranscripts`-shaped boundary (`filter`/`orderBy`/`pagination`) so the eventual move to server-side is a `queryFn` swap. Implemented **client-side** for now (evaluator over loaded rows); the streaming `ReplicationService`/IndexedDB sync itself is unchanged.
- **Async content in react-query.** The log handles/previews/details live in the react-query cache (fed by the sync), not zustand — table *state* (sorting, visibility) stays in zustand. See `loglist-content-react-query.md`.
- **Inspect-local now, shared later.** Build the TanStack grid inside `apps/inspect`. A shared monorepo grid is the eventual target but is deliberately premature until inspect's filtering/sorting model is settled — sharing now risks baking in the wrong abstraction.
- **Phased, not all-at-once.** Stand up a basic, correct table first; layer features back in over subsequent phases.
- **One component first.** This effort converts **`LogListGrid`** (serves `tasks` + `logs`/folder modes). `SamplesGrid` (sample view, with rotated headers / variable row heights / follow-output) is a separate effort after.

Scout's `DataGrid` is the structural analog, **not** a drop-in: it's wired to scout's *server* datapath (`manualSorting: true` with server fetch; column filters emit a `SimpleCondition` query DSL) and lives in `apps/scout` with scout-only imports. Inspect sorts/filters loaded rows client-side, so we borrow scout's *structure* (virtualizer, header/cell rendering, resize, keyboard nav) and reimplement sort client-side.

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
| Keyboard navigation (arrows / Home / End / PgUp-Dn / Enter), scroll-into-view | **3** |
| Ctrl+F find band (`FindBandUI`) | **4** |
| Column resizing | **5** |
| Per-column filter UI (text/number/date popovers → `Condition`) + Reset Filters + filtered-count | later — evaluator/plumbing already built |
| Column reordering (header drag) | later |
| Column pinning (`type` icon col pinned-left) | later |
| Auto-fit-to-grid-width (`autoSizeStrategy: fitGridWidth`) + user-resize-override suppression | later |
| Multi-line/preformatted cell tooltips (model-roles, task-args JSON — was `PreformattedTooltip`, now native `title`) | later — or accept the drop (Q3) |
| Infinite scroll / true pagination (cursor shape exists; client fetches all) | later (server-side) |

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

## Later phases (sketch)

- **Phase 3 — Keyboard navigation.** Arrows/Home/End/PgUp-Dn/Enter + scroll-into-view; adapt scout's DataGrid keyboard handler to single-select semantics.
- **Phase 4 — Ctrl+F find.** Port `FindBandUI` + per-row search string built from visible columns' `textValue`/accessor (replacing AG's `getCellValue` cache); scroll-to-match + select.
- **Phase 5 — Column resizing.** TanStack `enableColumnResizing` + resizer UI (re-add the scout CSS).
- **Per-column filter UI.** The evaluator + API + persisted-state slot already accept `Condition`; remaining work is the header filter popovers (text/number/date → `SimpleCondition`), combine via AND, and the Reset-Filters/filtered-count chrome. Templates: scout's `ColumnFilterControl`/`useColumnFilter` (→ `SimpleCondition`) + `useFilterConditions`. When this lands, `filteredCount` reflects the filtered set and folder counts can fold in the filter.
- **Later — reordering, pinning, auto-fit-to-width.** As listed in the roadmap.

## Discovered additional work

- **Scout reconciliation (user-owned).** The query Pydantic models + TS builders are duplicated (scout's `_query/*` + `apps/scout/src/query/*` still exist). Follow-up: point scout at `@tsmono/inspect-common/query` and collapse to a single Python codegen source.
- **Server-side filter/sort + infinite scroll.** The whole point of the API boundary: replace `useLogsListingQuery`'s client `useMemo` (and the content-cache population) with a server `getLogsListing(dir, filter, orderBy, pagination)` query. The transitional `log-list/listing/` evaluator gets deleted then. `Pagination` is cursor-shaped already; infinite scroll arrives with the server move.
- **New-tab parity.** New-tab open only works from the task cell's `<a>` overlay (matches old AG behavior); a row-level Cmd/middle-click handler could generalize it.
- **`SamplesGrid` migration.** The sample view (rotated headers / variable row heights / follow-output) is still AG Grid — a separate effort, after which `ag-grid-*` deps + `ColumnSelectorPopover`'s AG coupling can be removed.

## Open questions

1. Persist **column widths** per scope too (alongside sorting in `gridStateByScope`), or leave widths transient? (Lands with phase 5 resizing.)
2. Multi-line tooltips: is dropping `PreformattedTooltip` (model-roles / task-args JSON now flow through native `title`) acceptable, or restore a custom tooltip later?
