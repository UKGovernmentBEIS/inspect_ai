import {
  ColumnFiltersState,
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";
import clsx from "clsx";
import { FC, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useStore } from "../../state/store";
import { ApplicationIcons } from "../appearance/icons";
import { LogItem } from "./LogItem";
import styles from "./LogListGrid.module.css";

interface LogListGridProps {
  items: LogItem[];
}

const columnHelper = createColumnHelper<LogItem>();

export const LogListGrid: FC<LogListGridProps> = ({ items }) => {
  // TODO: Convert to store state
  const [sorting, setSorting] = useState<SortingState>([]);
  const [filtering, setFiltering] = useState<ColumnFiltersState>([]);
  const [globalFilter, setGlobalFilter] = useState("");

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
        enableSorting: false,
        enableGlobalFilter: false,
        size: 40,
      }),
      columnHelper.display({
        id: "task",
        header: "Task",
        cell: (info) => {
          const item = info.row.original;
          const logFile = item.logFile;
          if (!logFile) {
            return <div className={styles.typeCell}>{item.name}</div>;
          }

          const headerInfo = logHeaders[logFile.name || ""];
          if (!headerInfo) {
            return <div className={styles.typeCell}>Loading...</div>;
          }
          return <div className={styles.typeCell}>{headerInfo.eval.task}</div>;
        },
        enableSorting: true,
        enableGlobalFilter: true,
      }),

      columnHelper.accessor("name", {
        id: "name",
        header: "Name",
        cell: (info) => {
          const item = info.row.original;
          return (
            <div className={styles.nameCell}>
              {item.url ? (
                <Link to={item.url} className={styles.logLink}>
                  {info.getValue()}
                </Link>
              ) : (
                info.getValue()
              )}
            </div>
          );
        },
        enableSorting: true,
        enableGlobalFilter: true,
      }),
      columnHelper.accessor("type", {
        id: "type",
        header: "Type",
        cell: (info) => (
          <div className={styles.typeCell}>
            {info.getValue() === "file" ? "File" : "Folder"}
          </div>
        ),
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
    },
    onSortingChange: setSorting,
    onColumnFiltersChange: setFiltering,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
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
                onClick={header.column.getToggleSortingHandler()}
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
