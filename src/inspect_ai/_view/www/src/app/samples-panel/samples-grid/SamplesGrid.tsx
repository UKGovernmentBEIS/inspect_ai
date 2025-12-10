import type {
  ColDef,
  GridApi,
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
import { useClientEvents } from "../../../state/clientEvents";
import { useStore } from "../../../state/store";
import { inputString } from "../../../utils/format";
import { debounce } from "../../../utils/sync";
import { join } from "../../../utils/uri";
import { useSamplesGridNavigation } from "../../routing/sampleNavigation";
import { DisplayedSample } from "../../types";
import styles from "./SamplesGrid.module.css";
import { SampleRow } from "./types";

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

// Sample Grid Props
interface SamplesGridProps {
  samplesPath?: string;
  gridRef?: RefObject<AgGridReact | null>;
  columns: ColDef<SampleRow>[];
}

// Sample Grid
export const SamplesGrid: FC<SamplesGridProps> = ({
  samplesPath,
  gridRef: externalGridRef,
  columns,
}) => {
  const logDetails = useStore((state) => state.logs.logDetails);
  const gridState = useStore((state) => state.logs.samplesListState.gridState);
  const setGridState = useStore((state) => state.logsActions.setGridState);
  const { navigateToSampleDetail } = useSamplesGridNavigation();
  const logDir = useStore((state) => state.logs.logDir);
  const setFilteredSampleCount = useStore(
    (state) => state.logActions.setFilteredSampleCount,
  );
  const setDisplayedSamples = useStore(
    (state) => state.logsActions.setDisplayedSamples,
  );
  const clearDisplayedSamples = useStore(
    (state) => state.logsActions.clearDisplayedSamples,
  );
  const clearSelectedSample = useStore(
    (state) => state.sampleActions.clearSelectedSample,
  );
  const previousSamplesPath = useStore(
    (state) => state.logs.samplesListState.previousSamplesPath,
  );
  const setPreviousSamplesPath = useStore(
    (state) => state.logsActions.setPreviousSamplesPath,
  );

  const loading = useStore((state) => state.app.status.loading);
  const syncing = useStore((state) => state.app.status.syncing);
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  const selectedSampleHandle = useStore(
    (state) => state.log.selectedSampleHandle,
  );

  const internalGridRef = useRef<AgGridReact>(null);
  const gridRef = externalGridRef || internalGridRef;
  const gridContainerRef = useRef<HTMLDivElement>(null);

  // Polling for updated log files
  const { startPolling, stopPolling } = useClientEvents();
  useEffect(() => {
    startPolling([]);
    return () => {
      stopPolling();
    };
  }, [startPolling, stopPolling]);

  // Clear grid state when samplesPath changes to a different path
  // Use store-persisted previousSamplesPath to survive component remounts
  const initialGridState = useMemo(() => {
    if (
      previousSamplesPath !== undefined &&
      previousSamplesPath !== samplesPath
    ) {
      // Clear displayed samples when path changes to a different path
      clearDisplayedSamples();
      const result = { ...gridState };
      delete result?.filter;
      return result;
    } else {
      return gridState;
    }
  }, [previousSamplesPath, samplesPath, clearDisplayedSamples, gridState]);

  // Update the previous samples path in the store after render
  useEffect(() => {
    if (samplesPath !== previousSamplesPath) {
      setPreviousSamplesPath(samplesPath);
    }
  }, [samplesPath, previousSamplesPath, setPreviousSamplesPath]);

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
  }, [logDetails, logDir, samplesPath]);

  useEffect(() => {
    gridContainerRef.current?.focus();
  }, []);

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
          input: inputString(sample.input).join("\n"),
          target: Array.isArray(sample.target)
            ? sample.target.join(", ")
            : sample.target,
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
    [gridRef, navigateToSampleDetail],
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

  const sampleRowId = (
    logFile: string,
    sampleId: string | number,
    epoch: number,
  ) => {
    return `${logFile}-${sampleId}-${epoch}`.replace(/\s+/g, "_");
  };

  // Helper function to select the current sample in the grid
  const selectCurrentSample = useCallback(() => {
    if (!gridRef.current?.api || !selectedSampleHandle || !selectedLogFile) {
      return;
    }

    const rowId = sampleRowId(
      selectedLogFile,
      selectedSampleHandle.id,
      selectedSampleHandle.epoch,
    );
    const node = gridRef.current.api.getRowNode(rowId);

    if (node) {
      // Select the row
      gridRef.current.api.deselectAll();
      node.setSelected(true);
      // Ensure it's visible
      gridRef.current.api.ensureNodeVisible(node, "middle");
    }
  }, [gridRef, selectedSampleHandle, selectedLogFile]);

  // Select the row when the sample handle changes
  useEffect(() => {
    selectCurrentSample();
  }, [selectedSampleHandle, selectedLogFile, selectCurrentSample]);

  // Keep track of the max column count to avoid redundant resizing
  const maxColCount = useRef(0);

  // Resize grid columns when columns prop changes (e.g., when columns are hidden/unhidden)
  useEffect(() => {
    resizeGridColumns();
  }, [columns, resizeGridColumns]);

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
          rowSelection={{ mode: "singleRow", checkboxes: false }}
          getRowId={(params) =>
            sampleRowId(
              params.data.logFile,
              params.data.sampleId,
              params.data.epoch,
            )
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

              const gridCurrentSamples = gridDisplayedSamples(
                gridRef.current.api,
              );
              setDisplayedSamples(gridCurrentSamples);
            }
          }}
          onRowClicked={handleRowClick}
          onFilterChanged={() => {
            if (gridRef.current?.api) {
              const displayedRowCount =
                gridRef.current.api.getDisplayedRowCount();
              setFilteredSampleCount(displayedRowCount);

              const newDisplayedSamples = gridDisplayedSamples(
                gridRef.current.api,
              );
              setDisplayedSamples(newDisplayedSamples);
            }
          }}
          onFirstDataRendered={() => {
            // Select the current sample when the grid first renders data
            selectCurrentSample();
            clearSelectedSample();
          }}
          loading={data.length === 0 && (loading > 0 || syncing)}
        />
      </div>
    </div>
  );
};

const gridDisplayedSamples = (
  gridApi: GridApi<SampleRow>,
): DisplayedSample[] => {
  const displayedSamples: DisplayedSample[] = [];
  const displayedRowCount = gridApi.getDisplayedRowCount();
  for (let i = 0; i < displayedRowCount; i++) {
    const node = gridApi.getDisplayedRowAtIndex(i);
    if (node?.data) {
      displayedSamples.push({
        logFile: node.data.logFile,
        sampleId: node.data.sampleId,
        epoch: node.data.epoch,
      });
    }
  }
  return displayedSamples;
};
