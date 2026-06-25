# LogListGrid: AG Grid → TanStack Table

## Context

The inspect viewer's collection views (tasks, folder/logs, sample) render with AG Grid. We're migrating them to TanStack Table — the engine `inspect_scout`'s transcripts panel already uses (`apps/scout/.../components/dataGrid/DataGrid.tsx`). Goals/constraints:

- **Surgical.** Don't touch the datapath (rows are already loaded; sort/filter stay client-side).
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
| Row selection highlight + click-to-navigate + Cmd/Shift/middle-click → new tab | **1** |
| Client-side sorting incl. folder-first + NaN-aware/date comparators, sort indicators | **2** |
| Sort state persistence per `scopeKey` | **2** |
| Keyboard navigation (arrows / Home / End / PgUp-Dn / Enter), scroll-into-view | **3** |
| Ctrl+F find band (`FindBandUI`) | **4** |
| Column resizing | **5** |
| Per-column filter popovers (text/number/date) + Reset Filters + filtered-count | later |
| Column reordering (header drag) | later |
| Column pinning (`type` icon col pinned-left) | later |
| Auto-fit-to-grid-width (`autoSizeStrategy: fitGridWidth`) + user-resize-override suppression | later |

Phase numbers past 1 are a planning order, not a contract; we can resequence as we learn. The point is the full set lands eventually.

## Phase 1 — Stand up the table (render + navigate)

Deliver an inspect-local TanStack grid that renders the logs and tasks views with correct content and lets the user click into a log. No sorting, persistence, find, keyboard nav, resizing, or filtering yet.

**New inspect-local grid** under `apps/inspect/src/app/shared/data-grid/`:

- **`DataGrid.tsx`** — generic `<TRow>` TanStack wrapper. `useReactTable` with `getCoreRowModel`, `columnVisibility` state, `@tanstack/react-virtual` for rows. Renders header + cells via `flexRender`. Fixed column widths from each column's `size`; horizontal scroll when total width exceeds the container (like scout). Row selection highlight + click handler: normal click navigates, Cmd/Ctrl/Shift/middle-click open in new tab. (No sort/resizer/keyboard wiring yet — those land in later phases; leave clean seams for them.)
- **`DataGrid.module.css`** — adapt scout's CSS module (drop drag/reorder/resizer classes for now). Reuse existing `shared/gridCells.module.css` for cell-content classes (`iconCell`, `numberCell`, `taskText`, `scoreCell`, …) referenced by cell renderers.
- **`columnTypes.ts`** — local `ExtendedColumnDef<TRow>`: `ColumnDef<TRow>` + `meta` (`align`), `minSize`/`maxSize`, `headerTitle`, `textValue`. (Add `meta.sortComparator` in phase 2; filter fields later.)

**Column porting** — translate `useLogListColumns` (`log-list/grid/columns/hooks.tsx`) from AG `ColDef<LogListRow>[]` to `ExtendedColumnDef<LogListRow>[]`:

- `field`/`colId` → column **`id`** set to the *same field key* (`type`, `task`, `score`, `score_<scorer>/<metric>`, `metric_<name>`, …) so the existing `columnVisibility` record and the Columns popover keep working unchanged.
- `valueGetter` → `accessorFn`; `cellRenderer`(`params.data`/`params.value`) → `cell: ({ row, getValue })`; fold `valueFormatter` into `cell`/`textValue`. `tooltipValueGetter` → cell `title`. `initialWidth`→`size`, `min/maxWidth`→`minSize`/`maxSize`.
- Keep the comparator on the AG side for now (carry as `meta.sortComparator`, unused until phase 2) so we don't have to revisit each column.
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

## Later phases (sketch)

- **Phase 2 — Sorting + persistence.** `manualSorting: true`; `LogListGrid` `useMemo`s sorted data from `(data, sorting)` using each column's `meta.sortComparator` wrapped by the existing **`createFolderFirstComparator`** + **`comparators`** (`shared/gridComparators.ts`), reused near-verbatim. Direction is known to us, so folder-pinning stays correct in both directions (TanStack's built-in sort can't do this — it negates the whole comparator on desc). DataGrid renders sort-click + asc/desc indicators. Persist sort per `scopeKey`: replace `gridStateByScope: Record<string, GridState>` in `state/types.ts` with a new TanStack-shaped key (e.g. `logListSortByScope: Record<string, SortingState>`); drop the `ag-grid-community` `GridState` import. New key (not reinterpreting the old one) avoids reading stale AG state.
- **Phase 3 — Keyboard navigation.** Arrows/Home/End/PgUp-Dn/Enter + scroll-into-view; adapt scout's DataGrid keyboard handler to single-select semantics.
- **Phase 4 — Ctrl+F find.** Port `FindBandUI` + per-row search string built from visible columns' `textValue`/accessor (replacing AG's `getCellValue` cache); scroll-to-match + select.
- **Phase 5 — Column resizing.** TanStack `enableColumnResizing` + resizer UI (re-add the scout CSS).
- **Later — filtering, reordering, pinning, auto-fit-to-width.** As listed in the roadmap.

## Open questions

1. Phase 2: persist **column widths** per scope too, or sort-only? (Lean sort-only initially.)
2. Existing Playwright tests drive the AG api (`window.__inspectGridApi`) for sort/filter. Rewrite to drive TanStack/DOM, or expose a minimal test handle? (Addressed alongside phase 2/filtering, not phase 1.)
