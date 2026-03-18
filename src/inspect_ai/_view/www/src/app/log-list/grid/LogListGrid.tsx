import type {
  CellMouseDownEvent,
  GridColumnsChangedEvent,
  IRowNode,
  RowClickedEvent,
  StateUpdatedEvent,
} from "ag-grid-community";
import { themeBalham } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import clsx from "clsx";
import {
  FC,
  KeyboardEvent as ReactKeyboardEvent,
  RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";

import { FindBandUI } from "../../../components/FindBandUI";
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

  // Find functionality state - store row IDs instead of IRowNode references to avoid memory leaks
  const [showFind, setShowFind] = useState(false);
  const [findTerm, setFindTerm] = useState("");
  const [matchIds, setMatchIds] = useState<string[]>([]);
  const [currentMatchIndex, setCurrentMatchIndex] = useState(0);
  const findInputRef = useRef<HTMLInputElement>(null);

  // Helper to close find bar and reset state
  const closeFind = useCallback(() => {
    setShowFind(false);
    setFindTerm("");
    setMatchIds([]);
    setCurrentMatchIndex(0);
  }, []);

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

      // Pre-compute searchable text for fast Cmd+F search
      row.searchText = [row.name, row.task, row.model, row.id]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

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

  const handleCellMouseDown = useCallback(
    (e: CellMouseDownEvent<LogListRow>) => {
      const mouseEvent = e.event as MouseEvent | undefined;
      if (mouseEvent?.button === 1 && e.data?.url) {
        mouseEvent.preventDefault();
        window.open(`#${e.data.url}`, "_blank");
      }
    },
    [],
  );

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

  // Find functionality - uses pre-computed searchText for O(1) lookup per row
  const performSearch = useCallback(
    (term: string) => {
      const api = gridRef.current?.api;
      if (!api || !term) {
        setMatchIds([]);
        setCurrentMatchIndex(0);
        return;
      }
      const lowerTerm = term.toLowerCase();
      const foundIds: string[] = [];
      api.forEachNode((node) => {
        const rowData = node.data;
        if (!rowData?.searchText) return;
        if (rowData.searchText.includes(lowerTerm)) {
          foundIds.push(rowData.id);
        }
      });
      setMatchIds(foundIds);
      setCurrentMatchIndex(0);
      if (foundIds.length > 0) {
        const firstNode = api.getRowNode(foundIds[0]);
        if (firstNode) {
          api.deselectAll();
          api.ensureNodeVisible(firstNode, "middle");
          firstNode.setSelected(true, true);
        }
      }
    },
    [gridRef],
  );

  const goToMatch = useCallback(
    (index: number) => {
      if (matchIds.length === 0) return;
      const idx =
        ((index % matchIds.length) + matchIds.length) % matchIds.length;
      setCurrentMatchIndex(idx);
      const api = gridRef.current?.api;
      if (!api) return;
      const node = api.getRowNode(matchIds[idx]);
      if (node) {
        api.deselectAll();
        api.ensureNodeVisible(node, "middle");
        node.setSelected(true, true);
      }
    },
    [matchIds, gridRef],
  );

  const handleInputKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Escape") {
        closeFind();
      } else if (e.key === "Enter") {
        e.preventDefault();
        goToMatch(currentMatchIndex + (e.shiftKey ? -1 : 1));
      }
    },
    [goToMatch, currentMatchIndex, closeFind],
  );

  useEffect(() => {
    const handleFindKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "f") {
        e.preventDefault();
        e.stopPropagation();
        setShowFind(true);
        setTimeout(() => findInputRef.current?.focus(), 100);
      }
      if (e.key === "Escape" && showFind) {
        closeFind();
      }
    };
    document.addEventListener("keydown", handleFindKeyDown, true);
    return () =>
      document.removeEventListener("keydown", handleFindKeyDown, true);
  }, [closeFind, showFind]);

  useEffect(() => {
    if (findTerm) {
      performSearch(findTerm);
    } else {
      setMatchIds([]);
      setCurrentMatchIndex(0);
    }
  }, [findTerm, performSearch]);

  return (
    <div className={clsx(styles.gridWrapper)}>
      {showFind && (
        <FindBandUI
          inputRef={findInputRef}
          value={findTerm}
          onChange={() => setFindTerm(findInputRef.current?.value ?? "")}
          onKeyDown={handleInputKeyDown}
          onClose={closeFind}
          onPrevious={() => goToMatch(currentMatchIndex - 1)}
          onNext={() => goToMatch(currentMatchIndex + 1)}
          disableNav={matchIds.length === 0}
          noResults={!!findTerm && matchIds.length === 0}
          matchCount={findTerm ? matchIds.length : undefined}
          matchIndex={findTerm ? currentMatchIndex : undefined}
        />
      )}
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
          onCellMouseDown={handleCellMouseDown}
          onSortChanged={handleSortChanged}
          onFilterChanged={handleFilterChanged}
          loading={data.length === 0 && (loading > 0 || syncing)}
        />
      </div>
    </div>
  );
};
