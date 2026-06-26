# Log list: query types + client filter/sort, content in react-query

Part of the AG Grid → TanStack migration (see `loglistgrid-tanstack.md`). This step moves toward sorting/filtering behind a `getTranscripts`-style API and takes the log list's async **content** out of zustand.

## What shipped

### Shared query DSL → `@tsmono/inspect-common`
The `Condition`/`Operator`/`LogicalOperator`/`OrderBy`/`Pagination` types are **OpenAPI codegen output**, not hand-written. Scout's Pydantic query models were **copied** into inspect's Python (`src/inspect_ai/_view/_query/{condition,order_by,pagination}.py`) and emitted into `inspect-openapi.json` via `RootModel`-style stub endpoints in `schema.py` (the existing `Content`/`Event` pattern), so they flow through codegen into `@tsmono/inspect-common/src/types/generated.ts`. Scout's `ConditionBuilder`/`Column` builders were ported into `@tsmono/inspect-common/src/query` (new `./query` export).

> **Follow-up (user-owned):** reconcile scout — consume the shared inspect-common types/builders and collapse the duplicated Pydantic models onto one codegen path.

### Client-side listing query (inspect, transitional)
`apps/inspect/src/app/log-list/listing/`: `evaluateCondition` + `compareByOrderBy` + `paginate` composed by `applyListingQuery`, and the `useLogsListingQuery` hook (currently a `useMemo` over reactive rows; becomes a server `useQuery` when inspect moves filter/sort server-side). Column sort metadata (`meta.sortComparator`, value-only, reusing `gridComparators` primitives) + `getValue`/`getComparator` accessors come from `useLogListColumns`. **Deleted when inspect goes server-side.**

### Content out of zustand → react-query cache (fed by existing sync)
The log handles/previews/details now live in the react-query cache, not zustand:
- `state/queryClient.ts` — shared `QueryClient` singleton (App + non-React sync).
- `state/logsContent.ts` — `logsContentKey(dir)`, `setLogHandles`/`mergeLogPreviews`/`mergeLogDetails` (via `setQueryData`), `useLogsContent` + selectors, `getLogsContent`.
- The `ReplicationService`/IndexedDB streaming sync is unchanged; the `logsSlice` content actions are thin **shims** into the cache (so the sync context, `logSlice`, and `App.tsx` callers are untouched). `getSelectedLog`/`setSelectedLogFile` read handles from the cache.
- `logs`/`logPreviews`/`logDetails` dropped from `LogsState`; dead persist filter removed. All consumers (`state/hooks.ts`, `LogsPanel`, `LogListGrid`, `useLogListColumns`, `SamplesPanel`, `useLoadLog`, `LogViewLayout`) read via `useLogsContent`.

## Verified
`tsc`/eslint/prettier clean; 489 unit tests (incl. new `query`/`listing` suites); `top-level-views` e2e 8/8 (log list renders + navigates through the cache). Regenerate check: `python src/inspect_ai/_view/schema.py` touches only `inspect-openapi.json` + `generated.ts`.

## Remaining (follow-on)
Wire the sort/filter feature, sourcing rows from `useLogsContent` → `useLogsListingQuery`:
1. DataGrid sort-header wiring (click/indicators/`onSortingChange`).
2. Per-scope table-state slice in zustand (sorting; replaces AG `gridStateByScope`).
3. Panel rewire: build rows → `useLogsListingQuery` → render; logs-mode folder grouping from the filtered set (drop folder-first comparator); `filteredCount` from `total_count`.
4. Re-enable e2e sort assertions.
