import {
  ColumnFiltersState,
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";
import clsx from "clsx";
import { FC, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { firstMetric } from "../../scoring/metrics";
import { usePagination } from "../../state/hooks";
import { useStore } from "../../state/store";
import { formatPrettyDecimal } from "../../utils/format";
import { ApplicationIcons } from "../appearance/icons";
import { FileLogItem, FolderLogItem } from "./LogItem";
import styles from "./LogListGrid.module.css";
import { kLogsPaginationId } from "./LogsPanel";

interface LogListGridProps {
  items: Array<FileLogItem | FolderLogItem>;
}

const columnHelper = createColumnHelper<FileLogItem | FolderLogItem>();

export const LogListGrid: FC<LogListGridProps> = ({ items }) => {
  // TODO: Convert to store state
  const [sorting, setSorting] = useState<SortingState>([
    { id: "icon", desc: true },
    { id: "task", desc: false },
  ]);
  const [filtering, setFiltering] = useState<ColumnFiltersState>([]);
  const [globalFilter, setGlobalFilter] = useState("");

  const { page, itemsPerPage } = usePagination(kLogsPaginationId);

  const logHeaders = useStore((state) => state.logs.logHeaders);

  const columns = useMemo(
    () => [
      columnHelper.accessor("type", {
        id: "icon",
        header: "",
        cell: (info) => (
          <div className={styles.iconCell}>
            <i
              className={clsx(
                info.getValue() === "file"
                  ? ApplicationIcons.file
                  : ApplicationIcons.folder,
              )}
            />
          </div>
        ),
        enableSorting: true,
        enableGlobalFilter: false,
        size: 40,
        sortingFn: (rowA, rowB) => {
          const typeA = rowA.original.type;
          const typeB = rowB.original.type;

          return typeA.localeCompare(typeB);
        },
      }),
      columnHelper.accessor("name", {
        id: "task",
        header: "Task",
        cell: (info) => {
          const item = info.row.original as FileLogItem | FolderLogItem;
          const value =
            item.type === "file"
              ? logHeaders[item.logFile?.name || ""]?.eval.task || item.name
              : item.name;
          return (
            <div className={styles.nameCell}>
              {item.url ? (
                <Link to={item.url} className={styles.logLink}>
                  {value}
                </Link>
              ) : (
                value
              )}
            </div>
          );
        },
        enableSorting: true,
        enableGlobalFilter: true,
        sortingFn: (rowA, rowB) => {
          const itemA = rowA.original as FileLogItem | FolderLogItem;
          const itemB = rowB.original as FileLogItem | FolderLogItem;

          const valueA =
            itemA.type === "file"
              ? logHeaders[itemA.logFile?.name || ""]?.eval.task || itemA.name
              : itemA.name;
          const valueB =
            itemB.type === "file"
              ? logHeaders[itemB.logFile?.name || ""]?.eval.task || itemB.name
              : itemB.name;

          return valueA.localeCompare(valueB);
        },
      }),

      columnHelper.accessor("name", {
        id: "completed",
        header: "Completed",
        cell: (info) => {
          const item = info.row.original;
          const header =
            item.type === "file"
              ? logHeaders[item?.logFile?.name || ""]
              : undefined;

          const completed = header?.stats?.completed_at;
          const time = completed ? new Date(completed) : undefined;
          const timeStr = time
            ? `${time.toDateString()}
    ${time.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    })}`
            : "";

          return <div className={styles.nameCell}>{timeStr}</div>;
        },
        enableSorting: true,
        enableGlobalFilter: true,
      }),
      columnHelper.accessor("name", {
        id: "model",
        header: "Model",
        cell: (info) => {
          const item = info.row.original;
          const header =
            item.type === "file"
              ? logHeaders[item?.logFile?.name || ""]
              : undefined;
          return (
            <div className={styles.nameCell}>{header?.eval.model || ""}</div>
          );
        },
        sortingFn: (rowA, rowB) => {
          const itemA = rowA.original as FileLogItem | FolderLogItem;
          const itemB = rowB.original as FileLogItem | FolderLogItem;

          const headerA =
            itemA.type === "file"
              ? logHeaders[itemA.logFile?.name || ""]
              : undefined;
          const headerB =
            itemB.type === "file"
              ? logHeaders[itemB.logFile?.name || ""]
              : undefined;

          const modelA = headerA?.eval.model || "";
          const modelB = headerB?.eval.model || "";

          return modelA.localeCompare(modelB);
        },

        enableSorting: true,
        enableGlobalFilter: true,
      }),
      columnHelper.accessor("name", {
        id: "score",
        header: "Score",
        cell: (info) => {
          const item = info.row.original;
          const header =
            item.type === "file"
              ? logHeaders[item?.logFile?.name || ""]
              : undefined;

          const metric =
            header && header.results ? firstMetric(header.results) : undefined;
          if (!metric) {
            return emptyCell();
          }
          return (
            <div className={styles.typeCell}>
              {metric ? formatPrettyDecimal(metric.value) : ""}
            </div>
          );
        },
        sortingFn: (rowA, rowB) => {
          const itemA = rowA.original as FileLogItem | FolderLogItem;
          const itemB = rowB.original as FileLogItem | FolderLogItem;

          const headerA =
            itemA.type === "file"
              ? logHeaders[itemA.logFile?.name || ""]
              : undefined;
          const headerB =
            itemB.type === "file"
              ? logHeaders[itemB.logFile?.name || ""]
              : undefined;

          const metricA =
            headerA && headerA.results
              ? firstMetric(headerA.results)
              : undefined;
          const metricB =
            headerB && headerB.results
              ? firstMetric(headerB.results)
              : undefined;

          return (metricA?.value || 0) - (metricB?.value || 0);
        },
        enableSorting: true,
        enableGlobalFilter: true,
        size: 40,
      }),
    ],
    [logHeaders],
  );

  const table = useReactTable({
    data: items,
    columns,
    state: {
      sorting,
      columnFilters: filtering,
      globalFilter,
      pagination: {
        pageIndex: page,
        pageSize: itemsPerPage,
      },
    },
    rowCount: items.length,
    onSortingChange: setSorting,
    onColumnFiltersChange: setFiltering,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <div className={styles.gridContainer}>
      <div className={styles.grid}>
        {/* Header */}
        <div className={styles.headerRow}>
          {table.getHeaderGroups().map((headerGroup) =>
            headerGroup.headers.map((header) => (
              <div
                key={header.id}
                className={clsx(styles.headerCell, {
                  [styles.sortable]: header.column.getCanSort(),
                })}
                onClick={(event) => {
                  console.log(
                    `Column ${header.id} canSort: ${header.column.getCanSort()}`,
                  );
                  header.column.getToggleSortingHandler()?.(event);
                }}
                style={{
                  gridColumn: `span ${header.column.id === "name" ? 1 : header.column.id === "icon" ? 1 : 1}`,
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
              </div>
            )),
          )}
        </div>

        {/* Body */}
        <div className={styles.bodyContainer}>
          {table.getRowModel().rows.map((row) => (
            <div key={row.id} className={styles.bodyRow}>
              {row.getVisibleCells().map((cell) => (
                <div
                  key={cell.id}
                  className={clsx(
                    styles.bodyCell,
                    styles[`${cell.column.id}Cell`],
                  )}
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

const emptyCell = () => {
  return <div className={styles.emptyCell}>-</div>;
};
