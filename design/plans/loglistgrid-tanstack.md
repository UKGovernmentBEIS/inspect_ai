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
| Multi-line/preformatted cell tooltips (model-roles, task-args JSON — was `PreformattedTooltip`, now native `title`) | later — or accept the drop (Q3) |

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

## Later phases (sketch)

- **Phase 2 — Sorting + persistence.** Wire the DataGrid's `sorting` state + sort-click/asc-desc indicators (add to the existing header render). Keep sorting out of TanStack's row model (`manualSorting: true`); `LogListGrid` `useMemo`s sorted data from `(data, sorting)`. Reconstruct comparators in `useLogListColumns` and attach via `meta.sortComparator` (folder-first + NaN-aware/date), reusing **`createFolderFirstComparator`** + **`comparators`** (`shared/gridComparators.ts`) — adapt their `IRowNode`-based signature to row-based, or wrap. Direction is known to us, so folder-pinning stays correct in both directions (TanStack's built-in sort can't — it negates the whole comparator on desc). Persist sort per `scopeKey`: replace the now-unused `gridStateByScope: Record<string, GridState>` (`state/types.ts` + `logsSlice.ts` + `useLogsListing`) with a TanStack-shaped key (e.g. `logListSortByScope: Record<string, SortingState>`); drop the `ag-grid-community` `GridState` import. New key (not reinterpreting the old one) avoids reading stale AG state.
- **Phase 3 — Keyboard navigation.** Arrows/Home/End/PgUp-Dn/Enter + scroll-into-view; adapt scout's DataGrid keyboard handler to single-select semantics.
- **Phase 4 — Ctrl+F find.** Port `FindBandUI` + per-row search string built from visible columns' `textValue`/accessor (replacing AG's `getCellValue` cache); scroll-to-match + select.
- **Phase 5 — Column resizing.** TanStack `enableColumnResizing` + resizer UI (re-add the scout CSS).
- **Later — filtering, reordering, pinning, auto-fit-to-width.** As listed in the roadmap.

## Open questions

1. Phase 2: persist **column widths** per scope too, or sort-only? (Lean sort-only initially. Column resizing itself is phase 5, so widths may not be persistable until then.)
2. Phase 2/filtering: rewrite the skipped `log-list-filters.spec.ts` to drive the TanStack grid via DOM/ARIA roles (the `__inspectGridApi` AG hook is gone), or expose a minimal test handle? Re-enable per-suite as sorting (phase 2) then filtering land.
3. Multi-line tooltips: is dropping `PreformattedTooltip` (model-roles / task-args JSON now flow through native `title`) acceptable, or restore a custom tooltip later?
