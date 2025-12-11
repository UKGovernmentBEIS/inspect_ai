import type { ColDef, ICellRendererParams } from "ag-grid-community";
import clsx from "clsx";
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { parseLogFileName } from "../../../../utils/evallog";
import { formatPrettyDecimal } from "../../../../utils/format";
import { basename } from "../../../../utils/path";
import { ApplicationIcons } from "../../../appearance/icons";
import { LogListRow } from "./types";

import iconStyles from "./Icon.module.css";
import taskStyles from "./Task.module.css";
import modelStyles from "./Model.module.css";
import scoreStyles from "./Score.module.css";
import statusStyles from "./Status.module.css";
import dateStyles from "./CompletedDate.module.css";
import fileNameStyles from "./FileName.module.css";
import emptyStyles from "./EmptyCell.module.css";

const EmptyCell = () => <div className={emptyStyles.emptyCell}>—</div>;

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
              <div className={iconStyles.iconCell}>
                <i className={clsx(ApplicationIcons.folder)} />
              </div>
            );
          }
          if (params.data?.displayIndex !== undefined) {
            return (
              <div className={iconStyles.numberCell}>
                {params.data.displayIndex}
              </div>
            );
          }
          return "";
        },
        comparator: (valueA, valueB, nodeA, nodeB) => {
          const rank = (t: string) => (t === "folder" ? 0 : 1);
          const r = rank(valueA) - rank(valueB);
          if (r !== 0) return r;
          const nameA = nodeA?.data?.name || "";
          const nameB = nodeB?.data?.name || "";
          return nameA.localeCompare(nameB);
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
            <div className={taskStyles.nameCell}>
              {item.type === "folder" && item.url ? (
                <Link
                  to={item.url}
                  className={taskStyles.folderLink}
                  title={item.name}
                >
                  {value}
                </Link>
              ) : (
                <span className={taskStyles.taskText}>{value}</span>
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
            return <div className={modelStyles.modelCell}>{item.model}</div>;
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
            <div className={scoreStyles.scoreCell}>
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
              ? statusStyles.started
              : status === "error"
                ? statusStyles.error
                : status === "started"
                  ? statusStyles.started
                  : status === "cancelled"
                    ? statusStyles.cancelled
                    : statusStyles.success;

          return (
            <div className={statusStyles.statusCell}>
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
          return <div className={dateStyles.dateCell}>{timeStr}</div>;
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
            <div className={fileNameStyles.nameCell}>
              {item.url ? (
                <Link to={item.url} className={fileNameStyles.fileLink}>
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
