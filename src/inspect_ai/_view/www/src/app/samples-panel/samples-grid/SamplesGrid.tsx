import type {
  ColDef,
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
import { FC, RefObject, useCallback, useEffect, useMemo, useRef } from "react";
import { Input, Status } from "../../../@types/log";
import { usePrevious } from "../../../state/hooks";
import { useStore } from "../../../state/store";
import { filename } from "../../../utils/path";
import { debounce } from "../../../utils/sync";
import { join } from "../../../utils/uri";
import { useSamplesGridNavigation } from "../../routing/sampleNavigation";
import styles from "./SamplesGrid.module.css";

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

interface SamplesGridProps {
  samplesPath?: string;
  gridRef?: RefObject<AgGridReact | null>;
}

// Flattened row data for the grid
interface SampleRow {
  logFile: string;
  task: string;
  model: string;
  status?: Status;
  sampleId: string | number;
  epoch: number;
  input: string;
  target: string;
  error?: string;
  limit?: string;
  retries?: number;
  completed?: boolean;
  [key: string]: any; // For dynamic score columns
}

// Helper to convert Input to string
const formatInput = (input: Input): string => {
  if (typeof input === "string") return input;
  if (Array.isArray(input)) {
    return input
      .map((item) => {
        if (typeof item === "string") return item;
        if (item?.content) return item.content;
        return JSON.stringify(item);
      })
      .join(" ");
  }
  return JSON.stringify(input);
};

// Helper to convert Target to string
const formatTarget = (target: any): string => {
  if (typeof target === "string") return target;
  if (Array.isArray(target)) return target.join(", ");
  return JSON.stringify(target);
};

// Helper to format logFile path to show only relative path
const formatLogFilePath = (logFile: string): string => {
  return filename(logFile);
};

export const SamplesGrid: FC<SamplesGridProps> = ({
  samplesPath,
  gridRef: externalGridRef,
}) => {
  const logDetails = useStore((state) => state.logs.logDetails);
  const gridState = useStore((state) => state.logs.samplesListState.gridState);
  const setGridState = useStore((state) => state.logsActions.setGridState);
  const { navigateToSampleDetail } = useSamplesGridNavigation();
  const logDir = useStore((state) => state.logs.logDir);
  const setFilteredSampleCount = useStore(
    (state) => state.logActions.setFilteredSampleCount,
  );

  const internalGridRef = useRef<AgGridReact>(null);
  const gridRef = externalGridRef || internalGridRef;
  const gridContainerRef = useRef<HTMLDivElement>(null);

  // Clear grid state when samplesPath changes
  const prevSamplesPath = usePrevious(samplesPath);
  const initialGridState = useMemo(() => {
    if (prevSamplesPath !== samplesPath) {
      const result = { ...gridState };
      delete result?.filter;
      return result;
    } else {
      return gridState;
    }
  }, [gridState, prevSamplesPath]);

  // Filter logDetails based on samplesPath
  const filteredLogDetails = useMemo(() => {
    if (!samplesPath) {
      return logDetails; // Show all samples when no path is specified
    }

    const samplesPathAbs = join(samplesPath, logDir);

    return Object.entries(logDetails).reduce(
      (acc, [logFile, details]) => {
        // Check if the logFile starts with the samplesPath
        if (logFile.startsWith(samplesPathAbs)) {
          acc[logFile] = details;
        }
        return acc;
      },
      {} as typeof logDetails,
    );
  }, [logDetails, samplesPath]);

  // Transform logDetails into flat rows
  const data = useMemo(() => {
    const rows: SampleRow[] = [];

    Object.entries(filteredLogDetails).forEach(([logFile, details]) => {
      details.sampleSummaries.forEach((sample) => {
        const row: SampleRow = {
          logFile,
          task: details.eval.task || "",
          model: details.eval.model || "",
          status: details.status,
          sampleId: sample.id,
          epoch: sample.epoch,
          input: formatInput(sample.input),
          target: formatTarget(sample.target),
          error: sample.error,
          limit: sample.limit,
          retries: sample.retries,
          completed: sample.completed || false,
        };

        // Add scores as individual fields
        if (sample.scores) {
          Object.entries(sample.scores).forEach(([scoreName, score]) => {
            row[`score_${scoreName}`] = score.value;
          });
        }

        rows.push(row);
      });
    });

    return rows;
  }, [filteredLogDetails]);

  // Detect all unique score names across all samples
  const scoreMap = useMemo(() => {
    const scoreTypes: Record<string, string> = {};

    for (const details of Object.values(filteredLogDetails)) {
      for (const sample of details.sampleSummaries) {
        if (sample.scores) {
          for (const [name, score] of Object.entries(sample.scores)) {
            scoreTypes[name] = typeof score.value;
          }
        }
      }
    }
    return scoreTypes;
  }, [filteredLogDetails]);

  // Check if any sample has error, limit, or retries
  const hasError = useMemo(() => data.some((row) => row.error), [data]);
  const hasLimit = useMemo(() => data.some((row) => row.limit), [data]);
  const hasRetries = useMemo(() => data.some((row) => row.retries), [data]);

  // Create column definitions
  const columns = useMemo((): ColDef<SampleRow>[] => {
    const baseColumns: ColDef<SampleRow>[] = [
      {
        headerName: "#",
        valueGetter: (params) => {
          if (
            params.node?.rowIndex !== null &&
            params.node?.rowIndex !== undefined
          ) {
            return params.node.rowIndex + 1;
          }
          return "";
        },
        initialWidth: 80,
        minWidth: 50,
        maxWidth: 80,
        sortable: false,
        filter: false,
        resizable: false,
        pinned: "left",
      },
      {
        field: "task",
        headerName: "Task",
        initialWidth: 150,
        minWidth: 100,
        sortable: true,
        filter: true,
        resizable: true,
      },
      {
        field: "model",
        headerName: "Model",
        initialWidth: 150,
        minWidth: 100,
        sortable: true,
        filter: true,
        resizable: true,
      },
      {
        field: "sampleId",
        headerName: "Sample ID",
        initialWidth: 120,
        minWidth: 100,
        sortable: true,
        filter: true,
        resizable: true,
        valueGetter: (params) => String(params.data?.sampleId ?? ""),
      },
      {
        field: "epoch",
        headerName: "Epoch",
        initialWidth: 70,
        minWidth: 70,
        sortable: true,
        filter: true,
        resizable: true,
        cellStyle: { textAlign: "center" },
      },

      {
        field: "input",
        headerName: "Input",
        initialWidth: 250,
        minWidth: 150,
        sortable: true,
        filter: true,
        resizable: true,
        cellStyle: { overflow: "hidden", textOverflow: "ellipsis" },
      },
      {
        field: "status",
        headerName: "Status",
        initialWidth: 100,
        minWidth: 80,
        sortable: true,
        resizable: true,
        filter: "true",
      },
      {
        field: "logFile",
        headerName: "Log File",
        initialWidth: 200,
        minWidth: 150,
        sortable: true,
        filter: true,
        resizable: true,
        cellDataType: "date",
        valueParser: (params) => new Date(params.newValue),
        valueFormatter: (params) => formatLogFilePath(params.value),
      },
      {
        field: "target",
        headerName: "Target",
        initialWidth: 150,
        minWidth: 100,
        sortable: true,
        filter: true,
        resizable: true,
        cellStyle: { overflow: "hidden", textOverflow: "ellipsis" },
      },
    ];

    // Add score columns
    const scoreColumns: ColDef<SampleRow>[] = Object.keys(scoreMap).map(
      (scoreName) => {
        const scoreType = scoreMap[scoreName];
        return {
          field: `score_${scoreName}`,
          headerName: scoreName,
          initialWidth: 100,
          minWidth: 100,
          sortable: true,
          filter:
            scoreType === "number"
              ? "agNumberColumnFilter"
              : "agTextColumnFilter",

          resizable: true,
          valueFormatter: (params) => {
            // Format the score based upon its type
            const value = params.value;
            if (value === "" || value === null || value === undefined) {
              return "";
            }

            if (Array.isArray(value)) {
              return value.join(", ");
            } else if (typeof value === "object") {
              return JSON.stringify(value);
            } else if (typeof value === "number") {
              return value.toFixed(3);
            }
            return String(value);
          },
        };
      },
    );

    // Add optional columns
    const optionalColumns: ColDef<SampleRow>[] = [];

    if (hasError) {
      optionalColumns.push({
        field: "error",
        headerName: "Error",
        initialWidth: 150,
        minWidth: 100,
        sortable: true,
        filter: true,
        resizable: true,
        cellStyle: { overflow: "hidden", textOverflow: "ellipsis" },
      });
    }

    if (hasLimit) {
      optionalColumns.push({
        field: "limit",
        headerName: "Limit",
        initialWidth: 100,
        minWidth: 80,
        sortable: true,
        filter: true,
        resizable: true,
      });
    }

    if (hasRetries) {
      optionalColumns.push({
        field: "retries",
        headerName: "Retries",
        initialWidth: 80,
        minWidth: 60,
        sortable: true,
        filter: true,
        resizable: true,
      });
    }

    return [...baseColumns, ...scoreColumns, ...optionalColumns];
  }, [scoreMap, hasError, hasLimit, hasRetries]);

  const resizeGridColumns = useCallback(
    debounce(() => {
      // Trigger column sizing after grid is ready
      gridRef.current?.api?.sizeColumnsToFit();
    }, 10),
    [],
  );

  const handleRowClick = useCallback(
    (e: RowClickedEvent<SampleRow>) => {
      if (e.data && e.node && gridRef.current?.api) {
        // select the clicked row
        gridRef.current.api.deselectAll();
        e.node.setSelected(true);

        // Compute whether the click should open in a new window
        const mouseEvent = e.event as MouseEvent | undefined;
        const openInNewWindow =
          mouseEvent?.metaKey ||
          mouseEvent?.ctrlKey ||
          mouseEvent?.shiftKey ||
          mouseEvent?.button === 1;

        // Use setTimeout to allow grid state to update before navigation
        const logFile = e.data.logFile;
        const sampleId = e.data.sampleId;
        const epoch = e.data.epoch;
        setTimeout(() => {
          navigateToSampleDetail(logFile, sampleId, epoch, openInNewWindow);
        }, 10);
      }
    },
    [navigateToSampleDetail, gridRef],
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!gridRef.current?.api) {
        return;
      }

      // Don't handle keyboard events if focus is on an input, textarea, or select element
      const activeElement = document.activeElement;
      if (
        activeElement &&
        (activeElement.tagName === "INPUT" ||
          activeElement.tagName === "TEXTAREA" ||
          activeElement.tagName === "SELECT")
      ) {
        return;
      }

      // Get the currently selected row
      const selectedRows = gridRef.current.api.getSelectedNodes();
      const totalRows = gridRef.current.api.getDisplayedRowCount();

      // Determine current row index from selection or default to -1
      let currentRowIndex = -1;
      if (selectedRows.length > 0 && selectedRows[0].rowIndex !== null) {
        currentRowIndex = selectedRows[0].rowIndex;
      }

      let targetRowIndex: number | null = null;

      switch (e.key) {
        case "ArrowUp":
          e.preventDefault();
          if (e.metaKey || e.ctrlKey) {
            // Cmd/Ctrl + ArrowUp: Go to first row
            targetRowIndex = 0;
          } else {
            // ArrowUp: Go to previous row
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
            // Cmd/Ctrl + ArrowDown: Go to last row
            targetRowIndex = totalRows - 1;
          } else {
            // ArrowDown: Go to next row
            if (currentRowIndex === -1) {
              targetRowIndex = 0;
            } else {
              targetRowIndex = Math.min(totalRows - 1, currentRowIndex + 1);
            }
          }
          break;

        case "Home":
          e.preventDefault();
          // Home: Go to first row
          targetRowIndex = 0;
          break;

        case "End":
          e.preventDefault();
          // End: Go to last row
          targetRowIndex = totalRows - 1;
          break;

        case "PageUp":
          e.preventDefault();
          // PageUp: Go up 10 rows (or to first row)
          if (currentRowIndex === -1) {
            targetRowIndex = 0;
          } else {
            targetRowIndex = Math.max(0, currentRowIndex - 10);
          }
          break;

        case "PageDown":
          e.preventDefault();
          // PageDown: Go down 10 rows (or to last row)
          if (currentRowIndex === -1) {
            targetRowIndex = 0;
          } else {
            targetRowIndex = Math.min(totalRows - 1, currentRowIndex + 10);
          }
          break;

        case "Enter":
        case " ": {
          // Space key
          e.preventDefault();
          // Enter/Space: Open the selected row
          if (currentRowIndex !== -1) {
            const rowNode =
              gridRef.current.api.getDisplayedRowAtIndex(currentRowIndex);
            if (rowNode?.data) {
              const openInNewWindow = e.metaKey || e.ctrlKey || e.shiftKey;
              navigateToSampleDetail(
                rowNode.data.logFile,
                rowNode.data.sampleId,
                rowNode.data.epoch,
                openInNewWindow,
              );
            }
          }
          break;
        }

        default:
          return;
      }

      // Navigate to target row if set
      if (targetRowIndex !== null && targetRowIndex !== currentRowIndex) {
        const targetNode =
          gridRef.current.api.getDisplayedRowAtIndex(targetRowIndex);
        if (targetNode) {
          targetNode.setSelected(true, true); // true = select, true = clear other selections
          gridRef.current.api.ensureIndexVisible(targetRowIndex, "middle");
        }
      }
    },
    [navigateToSampleDetail],
  );

  // Set up keyboard event listener
  useEffect(() => {
    const gridElement = gridContainerRef.current;
    if (!gridElement) return;

    gridElement.addEventListener("keydown", handleKeyDown);

    return () => {
      gridElement.removeEventListener("keydown", handleKeyDown);
    };
  }, [handleKeyDown]);

  // Keep track of the max column count to avoid redundant resizing
  const maxColCount = useRef(0);

  return (
    <div className={styles.gridWrapper}>
      <div
        ref={gridContainerRef}
        style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }}
        tabIndex={0}
      >
        <AgGridReact<SampleRow>
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
          rowSelection="single"
          getRowId={(params) =>
            `${params.data.logFile}-${params.data.sampleId}-${params.data.epoch}`
          }
          onGridColumnsChanged={(e: GridColumnsChangedEvent<SampleRow>) => {
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
          onStateUpdated={(e: StateUpdatedEvent<SampleRow>) => {
            setGridState(e.state);
            if (gridRef.current?.api) {
              const displayedRowCount =
                gridRef.current.api.getDisplayedRowCount();
              setFilteredSampleCount(displayedRowCount);
            }
          }}
          onRowClicked={handleRowClick}
          onFilterChanged={() => {
            if (gridRef.current?.api) {
              const displayedRowCount =
                gridRef.current.api.getDisplayedRowCount();
              setFilteredSampleCount(displayedRowCount);
            }
          }}
        />
      </div>
    </div>
  );
};
