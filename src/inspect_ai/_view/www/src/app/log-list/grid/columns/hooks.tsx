import type { ColDef, ICellRendererParams } from "ag-grid-community";
import clsx from "clsx";
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { parseLogFileName } from "../../../../utils/evallog";
import { formatPrettyDecimal } from "../../../../utils/format";
import { basename } from "../../../../utils/path";
import { ApplicationIcons } from "../../../appearance/icons";
import { LogListRow } from "./types";

import styles from "./columns.module.css";

const EmptyCell = () => <div className={styles.emptyCell}>-</div>;

export const useLogListColumns = (
  _data: LogListRow[],
): ColDef<LogListRow>[] => {
  return useMemo((): ColDef<LogListRow>[] => {
    return [
      {
        field: "type",
        headerName: "#",
        initialWidth: 56,
        minWidth: 50,
        maxWidth: 72,
        suppressSizeToFit: true,
        sortable: true,
        filter: false,
        resizable: false,
        pinned: "left",
        cellRenderer: (params: ICellRendererParams<LogListRow>) => {
          const type = params.data?.type;
          if (type === "folder") {
            return (
              <div className={styles.iconCell}>
                <i className={clsx(ApplicationIcons.folder)} />
              </div>
            );
          }
          if (params.data?.displayIndex !== undefined) {
            return (
              <div className={styles.numberCell}>
                {params.data.displayIndex}
              </div>
            );
          }
          return "";
        },
      },
      {
        field: "task",
        headerName: "Task",
        initialWidth: 250,
        minWidth: 150,
        sortable: true,
        filter: true,
        resizable: true,
        colSpan: (params) => (params.data?.type === "folder" ? 100 : 1),
        valueGetter: (params) => {
          const item = params.data;
          if (!item) return "";
          if (item.type === "file") {
            return item.task || parseLogFileName(item.name).name;
          }
          return item.name;
        },
        cellRenderer: (params: ICellRendererParams<LogListRow>) => {
          const item = params.data;
          if (!item) return null;
          let value = item.name;
          if (item.type === "file") {
            value = item.task || parseLogFileName(item.name).name;
          }
          return (
            <div className={styles.nameCell}>
              {item.type === "folder" && item.url ? (
                <Link
                  to={item.url}
                  className={styles.folderLink}
                  title={item.name}
                >
                  {value}
                </Link>
              ) : (
                <span className={styles.taskText}>{value}</span>
              )}
            </div>
          );
        },
      },
      {
        field: "model",
        headerName: "Model",
        initialWidth: 300,
        minWidth: 100,
        maxWidth: 400,
        sortable: true,
        filter: true,
        resizable: true,
        cellRenderer: (params: ICellRendererParams<LogListRow>) => {
          const item = params.data;
          if (!item) return null;
          if (item.model) {
            return <div className={styles.modelCell}>{item.model}</div>;
          }
          return <EmptyCell />;
        },
      },
      {
        field: "score",
        headerName: "Score",
        initialWidth: 80,
        minWidth: 60,
        maxWidth: 120,
        sortable: true,
        filter: "agNumberColumnFilter",
        resizable: true,
        valueFormatter: (params) => {
          if (params.value === undefined || params.value === null) return "";
          return formatPrettyDecimal(params.value);
        },
        cellRenderer: (params: ICellRendererParams<LogListRow>) => {
          const item = params.data;
          if (!item || item.score === undefined) {
            return <EmptyCell />;
          }
          return (
            <div className={styles.scoreCell}>
              {formatPrettyDecimal(item.score)}
            </div>
          );
        },
      },
      {
        field: "status",
        headerName: "Status",
        initialWidth: 80,
        minWidth: 60,
        maxWidth: 100,
        sortable: true,
        filter: true,
        resizable: true,
        cellRenderer: (params: ICellRendererParams<LogListRow>) => {
          const item = params.data;
          if (!item) return null;

          const status = item.status;

          if (!status && item.type !== "pending-task") {
            return <EmptyCell />;
          }

          const icon =
            item.type === "pending-task"
              ? ApplicationIcons.pendingTask
              : status === "error"
                ? ApplicationIcons.error
                : status === "started"
                  ? ApplicationIcons.running
                  : status === "cancelled"
                    ? ApplicationIcons.cancelled
                    : ApplicationIcons.success;

          const clz =
            item.type === "pending-task"
              ? styles.started
              : status === "error"
                ? styles.error
                : status === "started"
                  ? styles.started
                  : status === "cancelled"
                    ? styles.cancelled
                    : styles.success;

          return (
            <div className={styles.statusCell}>
              <i className={clsx(icon, clz)} />
            </div>
          );
        },
        comparator: (valueA, valueB) => {
          if (!valueA && valueB) return 1;
          if (valueA && !valueB) return -1;
          if (!valueA && !valueB) return 0;
          return valueA.localeCompare(valueB);
        },
      },
      {
        field: "completedAt",
        headerName: "Completed",
        initialWidth: 200,
        minWidth: 120,
        maxWidth: 300,
        sortable: true,
        filter: true,
        resizable: true,
        valueGetter: (params) => {
          const completed = params.data?.completedAt;
          if (!completed) return "";
          const time = new Date(completed);
          return `${time.toDateString()} ${time.toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}`;
        },
        cellRenderer: (params: ICellRendererParams<LogListRow>) => {
          const item = params.data;
          if (!item || !item.completedAt) {
            return <EmptyCell />;
          }
          const time = new Date(item.completedAt);
          const timeStr = `${time.toDateString()} ${time.toLocaleTimeString(
            [],
            {
              hour: "2-digit",
              minute: "2-digit",
            },
          )}`;
          return <div className={styles.dateCell}>{timeStr}</div>;
        },
        comparator: (_valueA, _valueB, nodeA, nodeB) => {
          const completedA = nodeA.data?.completedAt;
          const completedB = nodeB.data?.completedAt;
          const timeA = new Date(completedA || 0).getTime();
          const timeB = new Date(completedB || 0).getTime();
          return timeA - timeB;
        },
      },
      {
        field: "name",
        headerName: "File Name",
        initialWidth: 600,
        minWidth: 150,
        sortable: true,
        filter: true,
        resizable: true,
        valueGetter: (params) => {
          const item = params.data;
          if (!item || item.type !== "file") return "";
          return basename(item.name);
        },
        cellRenderer: (params: ICellRendererParams<LogListRow>) => {
          const item = params.data;
          if (!item || item.type === "folder" || item.type === "pending-task") {
            return <EmptyCell />;
          }
          const value = basename(item.name);
          return (
            <div className={styles.nameCell}>
              {item.url ? (
                <Link to={item.url} className={styles.fileLink}>
                  {value}
                </Link>
              ) : (
                value
              )}
            </div>
          );
        },
        comparator: (_valueA, _valueB, nodeA, nodeB) => {
          const itemA = nodeA.data;
          const itemB = nodeB.data;
          if (!itemA || !itemB) return 0;
          if (itemA.type !== itemB.type) {
            return itemA.type === "folder" ? -1 : 1;
          }
          const a = basename(itemA.name);
          const b = basename(itemB.name);
          return a.localeCompare(b);
        },
      },
    ];
  }, []);
};
