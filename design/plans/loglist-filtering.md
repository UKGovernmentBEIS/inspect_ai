# Log list: per-column filter UI

Phase 3 of the AG Grid → TanStack migration (see `loglistgrid-tanstack.md`). Restores the per-column filtering origin/main had on the AG grid, on the TanStack DataGrid.

## Behavior

Each filterable log-list column has a **funnel button hidden until the header is hovered**, staying lit when that column has an active filter. Clicking it opens a per-type popover (text / number / date) that builds a `SimpleCondition`; filtering runs client-side over the loaded rows. Filter state persists per scope (mode + directory). A **Reset Filters** navbar button clears the current scope's filters; the Columns popover flags filtered columns and clears a column's filter when it's hidden.

## Architecture

### Shared editor — `@tsmono/inspect-components/columnFilter`

Scout's `columnFilter/` editor ported into `@tsmono/inspect-components` (shared, not inspect-local): `ColumnFilterControl` (funnel + `PopOver` + editor), `ColumnFilterButton`, `ColumnFilterEditor` (per-type inputs), `DurationInput`, `useColumnFilter` (operator tables, parse/build → `ConditionBuilder.simple`), `useColumnFilterPopover` (open/commit/cancel), `types.ts` (`FilterType`, `ColumnFilter`), CSS modules. Query imports point at `@tsmono/inspect-common/query`. The shared button is affordance-neutral (always rendered); the hover-reveal is layered by the consumer's header CSS, so scout's always-visible usage is unaffected.

- **Operators:** scout's full per-type set (`=`/`!=`/`LIKE`/`ILIKE`/`IN`/`BETWEEN`/`IS NULL`…). `buildCondition` ports verbatim (LIKE `%`-wrapping, IN list parsing, BETWEEN range, per-type value parsing).
- `FilterType = "string" | "number" | "boolean" | "date" | "datetime" | "duration" | "unknown"`; `ColumnFilter = { columnId; filterType; condition: SimpleCondition | null }`.

### Column metadata — `apps/inspect/.../data-grid`

`BaseColumnMeta` gains `filterable?: boolean` + `filterType?: FilterType`. `useLogListColumns` (`log-list/grid/columns/hooks.tsx`) marks columns filterable and assigns a `filterType` (derived from the sort comparator: number / date / string; the `type` icon column is not filterable) and exposes a `getFilterType(columnId)` accessor alongside `getValue`/`getComparator`.

### Type-aware evaluator — `log-list/listing/`

`evaluateCondition(row, condition, getValue, getFilterType?)` coerces both the row value and `condition.right` (and array/range elements) via the column's `filterType` before applying the operator: number/duration → `Number`; `date` → day-truncated epoch; `datetime` → epoch; boolean → bool; string/unknown → string. This makes `<`/`=`/`BETWEEN`/`IN` correct for numbers and day-granular for dates (matching origin/main's `agDateColumnFilter`). `getFilterType` threads through `applyListingQuery` and `useLogsListingQuery`. `combineFilters(columnFilters)` AND-combines the scope's column conditions into one `Condition` (`undefined` when empty).

### DataGrid + panel wiring

- `DataGrid` gains `columnFilters` + `onColumnFilterChange` props; in each header cell where `meta.filterable && meta.filterType` it renders `<ColumnFilterControl>` as a sibling of the sort-click region, wrapped in a hover-reveal div (`.headerCell:hover .headerFilter`, and `.headerFilterActive` when filtered).
- `LogListGrid` reads the scope's `columnFilters`, combines them, and passes `filter`/`getFilterType` to `useLogsListingQuery`; folders stay split out and pinned (filter applies to files); `filteredCount = folders + matching files`. Sort and filters are persisted together as `LogListGridState { sorting, columnFilters }`.
- `LogsPanel` restores the Reset Filters navbar button (shown when the scope has any active filter), passes `filteredFields` to `ColumnSelectorPopover`, and re-adds the hide-clears-filter merge in `handleColumnVisibilityChange`.

## Verification

- Unit (`listing.test.ts`): string `LIKE`/`IN`, number `IN` coercion, date `<`/`BETWEEN` (day-granularity), `IS NULL`, AND-combine — 17/17 pass.
- e2e (`top-level-views.spec.ts`, `Filtering` describe): funnel hover-reveal, apply a `LIKE` filter on the Task column, assert rows narrow + Reset Filters restores. 11/11 `top-level-views` pass. (Header/segment locators match by exact text, not accessible name, because the funnel's `aria-label` bleeds into the header's accessible name — see deferred ARIA audit.)
- typecheck / lint / format clean.

## Deferred / follow-ups

- **Autocomplete suggestions** — the editor passes `suggestions={[]}` (plain inputs). Wiring scout's `suggestions`/`onFilterColumnChange` needs an inspect API method to fetch per-column distinct values (analog of scout's `getTranscriptsColumnValues`).
- **Per-column clear affordance** — clearing one column's filter today means re-opening its funnel and blanking the value (empty value commits `null` → removed); the only one-click reset is the all-columns Reset Filters. A dedicated per-column Clear (e.g. in the popover when active) would be more discoverable. Scout/AG had no per-column clear either.
- **ARIA-label audit vs origin/main** — audit the DataGrid's roles/labels against origin/main's AG grid so accessibility/automation don't regress. Known wrinkle: the funnel's `aria-label="Filter <columnId>"` substring-collides with header/segment accessible names (e.g. "Filter totalSamples" matches a "Samples" query); reconsider the label scheme.
- **Filter-code export** (scout's Python/SQL "copy query") — not ported.
- `boolean`/`duration` editors port for free but are unused by current log-list columns (duration filters as `number`).
- **Scout reconciliation** onto the shared `columnFilter/` module + shared query types (tracked in the roadmap) — scout still has its own copies.
