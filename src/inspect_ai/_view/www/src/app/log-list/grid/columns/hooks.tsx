import type { ColDef, ICellRendererParams } from "ag-grid-community";
import clsx from "clsx";
import { useEffect, useMemo } from "react";
import { useStore } from "../../../../state/store";
import { parseLogFileName } from "../../../../utils/evallog";
import { formatDateTime, formatPrettyDecimal } from "../../../../utils/format";
import { basename } from "../../../../utils/path";
import { ApplicationIcons } from "../../../appearance/icons";
import {
  comparators,
  createFolderFirstComparator,
} from "../../../shared/gridComparators";
import { getFieldKey } from "../../../shared/gridUtils";
import { LogListRow } from "./types";

import sharedStyles from "../../../shared/gridCells.module.css";
import localStyles from "./columns.module.css";

const styles = { ...sharedStyles, ...localStyles };

const EmptyCell = () => <div>-</div>;

export const useLogListColumns = (): {
  columns: ColDef<LogListRow>[];
  setColumnVisibility: (visibility: Record<string, boolean>) => void;
} => {
  const columnVisibility = useStore(
    (state) => state.logs.listing.columnVisibility,
  );
  const setColumnVisibility = useStore(
    (state) => state.logsActions.setLogsColumnVisibility,
  );
  const logDetails = useStore((state) => state.logs.logDetails);

  // Detect all unique scorer names across all logs from their results
  const scorerMap = useMemo(() => {
    const scoreTypes: Record<string, string> = {};

    for (const details of Object.values(logDetails)) {
      if (details.results?.scores) {
        // scores is an array of EvalScore objects
        for (const evalScore of details.results.scores) {
          // Each EvalScore has metrics which is a record of EvalMetric
          if (evalScore.metrics) {
            for (const [metricName, metric] of Object.entries(
              evalScore.metrics,
            )) {
              scoreTypes[metricName] = typeof metric.value;
            }
          }
        }
      }
    }

    return scoreTypes;
  }, [logDetails]);

  // Auto-hide scorer columns by default if not explicitly set
  useEffect(() => {
    const scorerNames = Object.keys(scorerMap);
    if (scorerNames.length === 0) return;

    const needsUpdate = scorerNames.some(
      (name) => !(`score_${name}` in columnVisibility),
    );

    if (needsUpdate) {
      const newVisibility = { ...columnVisibility };
      for (const scorerName of scorerNames) {
        const field = `score_${scorerName}`;
        if (!(field in columnVisibility)) {
          newVisibility[field] = false;
        }
      }
      setColumnVisibility(newVisibility);
    }
  }, [scorerMap, columnVisibility, setColumnVisibility]);

  const allColumns = useMemo((): ColDef<LogListRow>[] => {
    const baseColumns: ColDef<LogListRow>[] = [
      {
        field: "type",
        headerName: "",
        initialWidth: 32,
        minWidth: 32,
        maxWidth: 32,
        suppressSizeToFit: true,
        sortable: true,
        filter: false,
        resizable: false,
        pinned: "left",
        cellRenderer: (params: ICellRendererParams<LogListRow>) => {
          const type = params.data?.type;
          const icon =
            type === "file" || type === "pending-task"
              ? ApplicationIcons.inspectFile
              : ApplicationIcons.folder;
          return (
            <div className={styles.iconCell}>
              <i className={clsx(icon)} />
            </div>
          );
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
                <span className={styles.folder}>{value}</span>
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
      },
      {
        field: "completedAt",
        headerName: "Completed",
        initialWidth: 130,
        minWidth: 80,
        maxWidth: 140,
        sortable: true,
        filter: true,
        resizable: true,
        cellDataType: "date",
        filterValueGetter: (params) => {
          if (!params.data?.completedAt) return undefined;
          const d = new Date(params.data.completedAt);
          return new Date(d.getFullYear(), d.getMonth(), d.getDate());
        },
        valueGetter: (params) => {
          const completed = params.data?.completedAt;
          if (!completed) return "";
          return formatDateTime(new Date(completed));
        },
        cellRenderer: (params: ICellRendererParams<LogListRow>) => {
          const completed = params.data?.completedAt;
          if (!completed) {
            return <EmptyCell />;
          }
          const timeStr = formatDateTime(new Date(completed));
          return <div className={styles.dateCell}>{timeStr}</div>;
        },
        comparator: createFolderFirstComparator<LogListRow>(comparators.date),
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
          return <div className={styles.nameCell}>{value}</div>;
        },
      },
    ];

    // Add scorer columns (currently only showing when we detect them)
    const scorerColumns: ColDef<LogListRow>[] = Object.keys(scorerMap).map(
      (scorerName) => {
        const scoreType = scorerMap[scorerName];
        return {
          field: `score_${scorerName}`,
          headerName: scorerName,
          initialWidth: 100,
          minWidth: 100,
          sortable: true,
          filter:
            scoreType === "number"
              ? "agNumberColumnFilter"
              : "agTextColumnFilter",
          resizable: true,
          valueFormatter: (params) => {
            const value = params.value;
            if (value === "" || value === null || value === undefined) {
              return "";
            }
            if (typeof value === "number") {
              return formatPrettyDecimal(value);
            }
            return String(value);
          },
          cellRenderer: (params: ICellRendererParams<LogListRow>) => {
            const value = params.value;
            if (value === undefined || value === null || value === "") {
              return <EmptyCell />;
            }
            return (
              <div className={styles.scoreCell}>
                {formatPrettyDecimal(value)}
              </div>
            );
          },
          comparator: createFolderFirstComparator<LogListRow>((valA, valB) => {
            if (typeof valA === "number" && typeof valB === "number") {
              return valA - valB;
            }
            return String(valA || "").localeCompare(String(valB || ""));
          }),
        } as ColDef<LogListRow>;
      },
    );

    return [...baseColumns, ...scorerColumns];
  }, [scorerMap]);

  const columns = useMemo((): ColDef<LogListRow>[] => {
    const columnsWithVisibility = allColumns.map((col: ColDef<LogListRow>) => {
      const field = getFieldKey(col);
      // Default to visible if not explicitly set, except for scorer columns
      const isScoreColumn = field.startsWith("score_");
      const isVisible =
        columnVisibility[field] ?? (isScoreColumn ? false : true);
      return {
        ...col,
        hide: !isVisible,
      };
    });

    return columnsWithVisibility;
  }, [allColumns, columnVisibility]);

  return {
    columns,
    setColumnVisibility,
  };
};
