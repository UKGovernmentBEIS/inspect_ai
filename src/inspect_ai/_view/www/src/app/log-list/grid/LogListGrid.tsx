import {
  ColumnFiltersState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  PaginationState,
  SortingState,
  Updater,
  useReactTable,
} from "@tanstack/react-table";
import clsx from "clsx";
import { FC, useCallback, useEffect, useMemo, useRef } from "react";

import { useLogs, useLogsListing, usePagination } from "../../../state/hooks";
import { useStore } from "../../../state/store";
import { FileLogItem, FolderLogItem } from "../LogItem";
import { kDefaultPageSize, kLogsPaginationId } from "../LogsPanel";
import styles from "./LogListGrid.module.css";
import { getColumns } from "./columns/columns";

interface LogListGridProps {
  items: Array<FileLogItem | FolderLogItem>;
}

export const LogListGrid: FC<LogListGridProps> = ({ items }) => {
  const {
    sorting,
    setSorting,
    filtering,
    setFiltering,
    globalFilter,
    setGlobalFilter,
    columnResizeMode,
    setFilteredCount,
    columnSizes,
    setColumnSize,
  } = useLogsListing();

  const { loadHeaders } = useLogs();

  const { page, itemsPerPage, setPage } = usePagination(
    kLogsPaginationId,
    kDefaultPageSize,
  );
  const headersLoading = useStore((state) => state.logs.logOverviewsLoading);
  const loading = useStore((state) => state.app.status.loading);
  const setWatchedLogs = useStore((state) => state.logsActions.setWatchedLogs);

  const logHeaders = useStore((state) => state.logs.logOverviews);
  const sortingRef = useRef(sorting);

  // Load all headers when needed (store handles deduplication)
  const loadAllHeadersForItems = useCallback(async () => {
    const logFiles = items
      .filter((item) => item.type === "file")
      .map((item) => item.logFile)
      .filter((file) => file !== undefined);

    await loadHeaders(logFiles);
    setWatchedLogs(logFiles);
  }, [loadHeaders, items, setWatchedLogs]);

  // Keep ref updated
  useEffect(() => {
    sortingRef.current = sorting;
  }, [sorting]);

  // Initial sort
  useEffect(() => {
    setSorting([{ id: "icon", desc: true }]);
  }, []);

  // Force re-sort when logHeaders change (affects task column sorting)
  useEffect(() => {
    // Only re-sort if we're currently sorting by a column that depends on logHeaders
    const currentSort = sortingRef.current?.find(
      (sort) =>
        sort.id === "task" || sort.id === "model" || sort.id === "score",
    );
    if (currentSort) {
      // Trigger a re-sort by updating the sorting state
      setSorting([...(sortingRef.current || [])]);
    }
  }, [logHeaders]);

  const columns = useMemo(() => {
    return getColumns();
  }, []);

  const table = useReactTable({
    data: items,
    columns,
    columnResizeMode: columnResizeMode || "onChange",
    state: {
      sorting,
      columnFilters: filtering,
      globalFilter,
      pagination: {
        pageIndex: page,
        pageSize: itemsPerPage,
      },
      columnSizing: columnSizes || {},
    },
    rowCount: items.length,
    onSortingChange: async (updater: Updater<SortingState>) => {
      await loadAllHeadersForItems();
      setSorting(
        typeof updater === "function" ? updater(sorting || []) : updater,
      );
    },
    onColumnFiltersChange: async (updater: Updater<ColumnFiltersState>) => {
      await loadAllHeadersForItems();
      setFiltering(
        typeof updater === "function" ? updater(filtering || []) : updater,
      );
    },
    onGlobalFilterChange: (updater: Updater<string>) => {
      setGlobalFilter(
        typeof updater === "function" ? updater(globalFilter || "") : updater,
      );
    },
    onPaginationChange: (updater: Updater<PaginationState>) => {
      const newPagination =
        typeof updater === "function"
          ? updater({ pageIndex: page, pageSize: itemsPerPage })
          : updater;
      setPage(newPagination.pageIndex);
    },
    onColumnSizingChange: (updater: Updater<Record<string, number>>) => {
      const newSizes =
        typeof updater === "function"
          ? updater(table.getState().columnSizing || {})
          : updater;
      for (const [columnId, size] of Object.entries(newSizes)) {
        setColumnSize(columnId, size);
      }
    },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    enableColumnResizing: true,
    autoResetPageIndex: false,
  });

  // Update filtered count in store when table filtering changes
  useEffect(() => {
    const filteredRowCount = table.getFilteredRowModel().rows.length;
    setFilteredCount(filteredRowCount);
  }, [table.getFilteredRowModel().rows.length, setFilteredCount]);

  // Load all headers when globalFilter changes
  useEffect(() => {
    if (globalFilter && globalFilter.trim()) {
      loadAllHeadersForItems();
    }
  }, [globalFilter, loadAllHeadersForItems]);

  // Load headers for current page (demand loading)
  useEffect(() => {
    const exec = async () => {
      const startIndex = page * itemsPerPage;
      const endIndex = startIndex + itemsPerPage;
      const currentPageItems = items.slice(startIndex, endIndex);

      const fileItems = currentPageItems.filter((item) => item.type === "file");
      const logFiles = fileItems
        .map((item) => item.logFile)
        .filter((file) => file !== undefined);

      // Only load headers for files that don't already have headers loaded
      const filesToLoad = logFiles.filter((file) => !logHeaders[file.name]);

      if (filesToLoad.length > 0) {
        await loadHeaders(filesToLoad);
      }

      setWatchedLogs(logFiles);
    };
    exec();
  }, [page, itemsPerPage, items, loadHeaders, setWatchedLogs, logHeaders]);

  const placeholderText = useMemo(() => {
    if (headersLoading || loading) {
      if (globalFilter) {
        return "searching...";
      } else {
        return "loading...";
      }
    } else {
      if (globalFilter) {
        return "no matching logs";
      } else {
        return "no logs";
      }
    }
  }, [headersLoading, loading, globalFilter]);

  return (
    <div className={styles.gridContainer}>
      <div className={styles.grid}>
        {/* Header */}
        <div
          className={styles.headerRow}
          style={{
            gridTemplateColumns:
              table
                .getHeaderGroups()[0]
                ?.headers.map((header) => `${header.getSize()}px`)
                .join(" ") || "40px 0.5fr 0.25fr 0.25fr 0.1fr",
          }}
        >
          {table.getHeaderGroups().map((headerGroup) =>
            headerGroup.headers.map((header) => (
              <div
                key={header.id}
                className={clsx(styles.headerCell, {
                  [styles.sortable]: header.column.getCanSort(),
                  [styles.resizing]: header.column.getIsResizing(),
                })}
                onClick={(event) => {
                  header.column.getToggleSortingHandler()?.(event);
                }}
                style={{
                  width: header.getSize(),
                  position: "relative",
                }}
              >
                {header.isPlaceholder
                  ? null
                  : flexRender(
                      header.column.columnDef.header,
                      header.getContext(),
                    )}
                {header.column.getCanSort() && (
                  <span className={styles.sortIndicator}>
                    {{
                      asc: " ↑",
                      desc: " ↓",
                    }[header.column.getIsSorted() as string] ?? ""}
                  </span>
                )}
                {header.column.getCanResize() && (
                  <div
                    onMouseDown={(e) => {
                      e.stopPropagation();
                      header.getResizeHandler()(e);
                    }}
                    onTouchStart={(e) => {
                      e.stopPropagation();
                      header.getResizeHandler()(e);
                    }}
                    onClick={(e) => {
                      e.stopPropagation();
                    }}
                    className={clsx(styles.resizer, {
                      [styles.isResizing]: header.column.getIsResizing(),
                    })}
                  />
                )}
              </div>
            )),
          )}
        </div>

        {/* Body */}
        <div className={styles.bodyContainer}>
          {table.getRowModel().rows.length === 0 && (
            <div className={styles.emptyMessage}>{placeholderText}</div>
          )}
          {table.getRowModel().rows.map((row) => (
            <div
              key={row.id}
              className={styles.bodyRow}
              style={{
                gridTemplateColumns: row
                  .getVisibleCells()
                  .map((cell) => `${cell.column.getSize()}px`)
                  .join(" "),
              }}
            >
              {row.getVisibleCells().map((cell) => (
                <div
                  key={cell.id}
                  className={clsx(
                    styles.bodyCell,
                    styles[`${cell.column.id}Cell`],
                  )}
                  style={{
                    width: cell.column.getSize(),
                  }}
                >
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
