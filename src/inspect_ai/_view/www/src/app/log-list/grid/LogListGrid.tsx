import type {
  GridColumnsChangedEvent,
  RowClickedEvent,
  StateUpdatedEvent,
} from "ag-grid-community";
import {
  AllCommunityModule,
  ModuleRegistry,
  themeBalham,
} from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import clsx from "clsx";
import { FC, useCallback, useEffect, useMemo, useRef } from "react";
import { useNavigate } from "react-router-dom";

import { useLogs, useLogsListing } from "../../../state/hooks";
import { useStore } from "../../../state/store";
import { FileLogItem, FolderLogItem, PendingTaskItem } from "../LogItem";
import styles from "./LogListGrid.module.css";
import { useLogListColumns } from "./columns/hooks";
import { LogListRow } from "./columns/types";

ModuleRegistry.registerModules([AllCommunityModule]);

interface LogListGridProps {
  items: Array<FileLogItem | FolderLogItem | PendingTaskItem>;
}

export interface LogListGridHandle {
  focus: () => void;
}

export const LogListGrid: FC<LogListGridProps> = ({ items }) => {
  const { gridState, setGridState, setFilteredCount } = useLogsListing();

  const { loadLogOverviews, loadAllLogOverviews } = useLogs();

  const loading = useStore((state) => state.app.status.loading);
  const syncing = useStore((state) => state.app.status.syncing);
  const setWatchedLogs = useStore((state) => state.logsActions.setWatchedLogs);

  const logPreviews = useStore((state) => state.logs.logPreviews);
  const navigate = useNavigate();
  const gridRef = useRef<AgGridReact<LogListRow>>(null);
  const gridContainerRef = useRef<HTMLDivElement>(null);

  const logFiles = useMemo(() => {
    return items
      .filter((item) => item.type === "file")
      .map((item) => item.log)
      .filter((file) => file !== undefined);
  }, [items]);

  const data: LogListRow[] = useMemo(() => {
    return items.map((item) => {
      const preview = item.type === "file" ? item.logPreview : undefined;
      return {
        id: item.id,
        name: item.name,
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
    });
  }, [items]);

  const columns = useLogListColumns(data);

  useEffect(() => {
    gridContainerRef.current?.focus();
  }, []);

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
              window.open(url, "_blank");
            } else {
              navigate(url);
            }
          }, 10);
        }
      }
    },
    [navigate],
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!gridRef.current?.api) {
        return;
      }

      const activeElement = document.activeElement;
      if (
        activeElement &&
        (activeElement.tagName === "INPUT" ||
          activeElement.tagName === "TEXTAREA" ||
          activeElement.tagName === "SELECT")
      ) {
        return;
      }

      const selectedRows = gridRef.current.api.getSelectedNodes();
      const totalRows = gridRef.current.api.getDisplayedRowCount();

      let currentRowIndex = -1;
      if (selectedRows.length > 0 && selectedRows[0].rowIndex !== null) {
        currentRowIndex = selectedRows[0].rowIndex;
      }

      let targetRowIndex: number | null = null;

      switch (e.key) {
        case "ArrowUp":
          e.preventDefault();
          if (e.metaKey || e.ctrlKey) {
            targetRowIndex = 0;
          } else {
            if (currentRowIndex === -1) {
              targetRowIndex = 0;
            } else {
              targetRowIndex = Math.max(0, currentRowIndex - 1);
            }
          }
          break;

        case "ArrowDown":
          e.preventDefault();
          if (e.metaKey || e.ctrlKey) {
            targetRowIndex = totalRows - 1;
          } else {
            if (currentRowIndex === -1) {
              targetRowIndex = 0;
            } else {
              targetRowIndex = Math.min(totalRows - 1, currentRowIndex + 1);
            }
          }
          break;

        case "Home":
          e.preventDefault();
          targetRowIndex = 0;
          break;

        case "End":
          e.preventDefault();
          targetRowIndex = totalRows - 1;
          break;

        case "PageUp":
          e.preventDefault();
          if (currentRowIndex === -1) {
            targetRowIndex = 0;
          } else {
            targetRowIndex = Math.max(0, currentRowIndex - 10);
          }
          break;

        case "PageDown":
          e.preventDefault();
          if (currentRowIndex === -1) {
            targetRowIndex = 0;
          } else {
            targetRowIndex = Math.min(totalRows - 1, currentRowIndex + 10);
          }
          break;

        case "Enter":
        case " ": {
          e.preventDefault();
          if (currentRowIndex !== -1) {
            const rowNode =
              gridRef.current.api.getDisplayedRowAtIndex(currentRowIndex);
            if (rowNode?.data?.url) {
              const openInNewWindow = e.metaKey || e.ctrlKey || e.shiftKey;
              if (openInNewWindow) {
                window.open(rowNode.data.url, "_blank");
              } else {
                navigate(rowNode.data.url);
              }
            }
          }
          break;
        }

        default:
          return;
      }

      if (targetRowIndex !== null && targetRowIndex !== currentRowIndex) {
        const targetNode =
          gridRef.current.api.getDisplayedRowAtIndex(targetRowIndex);
        if (targetNode) {
          targetNode.setSelected(true, true);
          gridRef.current.api.ensureIndexVisible(targetRowIndex, "middle");
        }
      }
    },
    [navigate],
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
  }, [loadAllLogOverviews, setWatchedLogs, logFiles, setFilteredCount]);

  const maxColCount = useRef(0);

  const resizeGridColumns = useMemo(() => {
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    return () => {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      timeoutId = setTimeout(() => {
        gridRef.current?.api?.sizeColumnsToFit();
      }, 10);
    };
  }, []);

  return (
    <div className={clsx(styles.gridWrapper)}>
      <div
        ref={gridContainerRef}
        style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }}
        tabIndex={0}
      >
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
          initialState={gridState}
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
