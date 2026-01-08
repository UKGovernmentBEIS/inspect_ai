import type {
  GridColumnsChangedEvent,
  IRowNode,
  RowClickedEvent,
  StateUpdatedEvent,
} from "ag-grid-community";
import { themeBalham } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import clsx from "clsx";
import { FC, RefObject, useCallback, useEffect, useMemo, useRef } from "react";
import { useNavigate } from "react-router-dom";

import { useLogs, useLogsListing } from "../../../state/hooks";
import { useStore } from "../../../state/store";
import "../../shared/agGrid";
import styles from "../../shared/gridCells.module.css";
import { createGridKeyboardHandler } from "../../shared/gridKeyboardNavigation";
import { createGridColumnResizer } from "../../shared/gridUtils";
import { FileLogItem, FolderLogItem, PendingTaskItem } from "../LogItem";
import { useLogListColumns } from "./columns/hooks";
import { LogListRow } from "./columns/types";

interface LogListGridProps {
  items: Array<FileLogItem | FolderLogItem | PendingTaskItem>;
  currentPath?: string;
  gridRef?: RefObject<AgGridReact<LogListRow> | null>;
}

export const LogListGrid: FC<LogListGridProps> = ({
  items,
  currentPath,
  gridRef: externalGridRef,
}) => {
  const {
    gridState,
    setGridState,
    setFilteredCount,
    previousLogPath,
    setPreviousLogPath,
  } = useLogsListing();

  const { loadLogOverviews, loadAllLogOverviews } = useLogs();

  const loading = useStore((state) => state.app.status.loading);
  const syncing = useStore((state) => state.app.status.syncing);
  const setWatchedLogs = useStore((state) => state.logsActions.setWatchedLogs);

  const logPreviews = useStore((state) => state.logs.logPreviews);
  const logDetails = useStore((state) => state.logs.logDetails);
  const navigate = useNavigate();
  const internalGridRef = useRef<AgGridReact<LogListRow>>(null);
  const gridRef = externalGridRef ?? internalGridRef;
  const gridContainerRef = useRef<HTMLDivElement>(null);

  const logFiles = useMemo(() => {
    return items
      .filter((item) => item.type === "file")
      .map((item) => item.log)
      .filter((file) => file !== undefined);
  }, [items]);

  const { columns } = useLogListColumns();

  const initialGridState = useMemo(() => {
    if (previousLogPath !== undefined && previousLogPath !== currentPath) {
      const result = { ...gridState };
      delete result.filter;
      return result;
    }
    return gridState;
  }, [currentPath, gridState, previousLogPath]);

  useEffect(() => {
    if (currentPath !== previousLogPath) {
      setPreviousLogPath(currentPath);
    }
  }, [currentPath, previousLogPath, setPreviousLogPath]);

  useEffect(() => {
    gridContainerRef.current?.focus();
  }, []);

  const data: LogListRow[] = useMemo(() => {
    return items.map((item) => {
      const preview = item.type === "file" ? item.logPreview : undefined;
      const details =
        item.type === "file" && item.log
          ? logDetails[item.log.name]
          : undefined;

      const row: LogListRow = {
        id: item.id,
        name: item.name,
        displayIndex:
          item.type === "file" || item.type === "pending-task"
            ? item.displayIndex
            : undefined,
        type: item.type,
        url: item.url,
        task: item.type === "file" ? preview?.task : item.name,
        model:
          item.type === "file"
            ? preview?.model
            : item.type === "pending-task"
              ? item.model
              : undefined,
        score: preview?.primary_metric?.value,
        status: preview?.status,
        completedAt: preview?.completed_at,
        itemCount: item.type === "folder" ? item.itemCount : undefined,
        log: item.type === "file" ? item.log : undefined,
      };

      // Add individual scorer columns from results
      if (details?.results?.scores) {
        for (const evalScore of details.results.scores) {
          if (evalScore.metrics) {
            for (const [metricName, metric] of Object.entries(
              evalScore.metrics,
            )) {
              row[`score_${metricName}`] = metric.value;
            }
          }
        }
      }

      return row;
    });
  }, [items, logDetails]);

  const handleRowClick = useCallback(
    (e: RowClickedEvent<LogListRow>) => {
      if (e.data && e.node && gridRef.current?.api) {
        gridRef.current.api.deselectAll();
        e.node.setSelected(true);

        const mouseEvent = e.event as MouseEvent | undefined;
        const openInNewWindow =
          mouseEvent?.metaKey ||
          mouseEvent?.ctrlKey ||
          mouseEvent?.shiftKey ||
          mouseEvent?.button === 1;

        const url = e.data.url;
        if (url) {
          setTimeout(() => {
            if (openInNewWindow) {
              window.open(`#${url}`, "_blank");
            } else {
              navigate(url);
            }
          }, 10);
        }
      }
    },
    [navigate, gridRef],
  );

  const handleOpenRow = useCallback(
    (rowNode: IRowNode<LogListRow>, e: KeyboardEvent) => {
      if (!rowNode.data?.url) {
        return;
      }
      const openInNewWindow = e.metaKey || e.ctrlKey || e.shiftKey;
      if (openInNewWindow) {
        window.open(`#${rowNode.data.url}`, "_blank");
      } else {
        navigate(rowNode.data.url);
      }
    },
    [navigate],
  );

  const handleKeyDown = useMemo(
    () =>
      createGridKeyboardHandler<LogListRow>({
        gridRef,
        onOpenRow: handleOpenRow,
      }),
    [gridRef, handleOpenRow],
  );

  useEffect(() => {
    const gridElement = gridContainerRef.current;
    if (!gridElement) return;

    gridElement.addEventListener("keydown", handleKeyDown);

    return () => {
      gridElement.removeEventListener("keydown", handleKeyDown);
    };
  }, [handleKeyDown]);

  useEffect(() => {
    const loadHeaders = async () => {
      const filesToLoad = logFiles.filter((file) => !logPreviews[file.name]);
      if (filesToLoad.length > 0) {
        await loadLogOverviews(filesToLoad);
      }
      setWatchedLogs(logFiles);
    };
    loadHeaders();
  }, [logFiles, loadLogOverviews, setWatchedLogs, logPreviews]);

  const handleSortChanged = useCallback(async () => {
    await loadAllLogOverviews();
    setWatchedLogs(logFiles);
  }, [loadAllLogOverviews, setWatchedLogs, logFiles]);

  const handleFilterChanged = useCallback(async () => {
    await loadAllLogOverviews();
    setWatchedLogs(logFiles);
    if (gridRef.current?.api) {
      const displayedRowCount = gridRef.current.api.getDisplayedRowCount();
      setFilteredCount(displayedRowCount);
    }
  }, [
    loadAllLogOverviews,
    setWatchedLogs,
    logFiles,
    setFilteredCount,
    gridRef,
  ]);

  const maxColCount = useRef(0);

  const resizeGridColumns = useRef(createGridColumnResizer(gridRef)).current;

  // Resize grid columns when columns prop changes (e.g., when columns are hidden/unhidden)
  useEffect(() => {
    resizeGridColumns();
  }, [columns, resizeGridColumns]);

  return (
    <div className={clsx(styles.gridWrapper)}>
      <div ref={gridContainerRef} className={styles.gridContainer} tabIndex={0}>
        <AgGridReact<LogListRow>
          ref={gridRef}
          rowData={data}
          animateRows={false}
          columnDefs={columns}
          defaultColDef={{
            sortable: true,
            filter: true,
            resizable: true,
          }}
          autoSizeStrategy={{ type: "fitGridWidth" }}
          headerHeight={25}
          rowSelection={{ mode: "singleRow", checkboxes: false }}
          getRowId={(params) => params.data.id}
          onGridColumnsChanged={(e: GridColumnsChangedEvent<LogListRow>) => {
            const cols = e.api.getColumnDefs();
            if (cols && cols?.length > maxColCount.current) {
              maxColCount.current = cols.length;
              resizeGridColumns();
            }
          }}
          onGridSizeChanged={resizeGridColumns}
          theme={themeBalham}
          enableCellTextSelection={true}
          initialState={initialGridState}
          suppressCellFocus={true}
          onStateUpdated={(e: StateUpdatedEvent<LogListRow>) => {
            setGridState(e.state);
            if (gridRef.current?.api) {
              const displayedRowCount =
                gridRef.current.api.getDisplayedRowCount();
              setFilteredCount(displayedRowCount);
            }
          }}
          onRowClicked={handleRowClick}
          onSortChanged={handleSortChanged}
          onFilterChanged={handleFilterChanged}
          loading={data.length === 0 && (loading > 0 || syncing)}
        />
      </div>
    </div>
  );
};
