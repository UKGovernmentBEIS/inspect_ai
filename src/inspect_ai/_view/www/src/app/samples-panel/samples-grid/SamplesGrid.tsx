import type {
  ColDef,
  GridApi,
  GridColumnsChangedEvent,
  IRowNode,
  RowClickedEvent,
  StateUpdatedEvent,
} from "ag-grid-community";
import { themeBalham } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { FC, RefObject, useCallback, useEffect, useMemo, useRef } from "react";
import { useClientEvents } from "../../../state/clientEvents";
import { useStore } from "../../../state/store";
import { inputString } from "../../../utils/format";
import { debounce } from "../../../utils/sync";
import { directoryRelativeUrl, join } from "../../../utils/uri";
import { useSamplesGridNavigation } from "../../routing/sampleNavigation";
import { DisplayedSample } from "../../types";
import "../../shared/agGrid";
import { createGridKeyboardHandler } from "../../shared/gridNavigation";
import styles from "./SamplesGrid.module.css";
import { SampleRow } from "./types";
import { samplesUrl } from "../../routing/url";

// Sample Grid Props
interface SamplesGridProps {
  samplesPath?: string;
  gridRef?: RefObject<AgGridReact<SampleRow> | null>;
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

  const internalGridRef = useRef<AgGridReact<SampleRow>>(null);
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
    const basePathAbs = samplesPath ? join(samplesPath, logDir) : logDir;
    const folders: SampleRow[] = [];
    const samples: SampleRow[] = [];
    const seenFolders = new Set<string>();
    let displayIndex = 1;

    Object.entries(filteredLogDetails).forEach(([logFile, details]) => {
      const relToBase = directoryRelativeUrl(logFile, basePathAbs);
      const relativeSegments = relToBase.split("/").filter(Boolean);
      if (relativeSegments.length > 1) {
        const folderName = decodeURIComponent(relativeSegments[0]);
        if (!seenFolders.has(folderName)) {
          seenFolders.add(folderName);
          folders.push({
            type: "folder",
            name: folderName,
            logFile: join(folderName, logDir),
            task: folderName,
            model: "",
            sampleId: "",
            epoch: 0,
            input: "",
            target: "",
            url: samplesUrl(join(folderName, samplesPath || ""), logDir),
          });
        }
      }

      details.sampleSummaries.forEach((sample) => {
        const row: SampleRow = {
          type: "sample",
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
          displayIndex: displayIndex++,
        };

        if (sample.scores) {
          Object.entries(sample.scores).forEach(([scoreName, score]) => {
            row[`score_${scoreName}`] = score.value;
          });
        }

        samples.push(row);
      });
    });

    // Return folders first, then samples
    return [...folders, ...samples];
  }, [filteredLogDetails, logDir, samplesPath]);

  const resizeGridColumns = useMemo(
    () =>
      debounce(() => {
        // Trigger column sizing after grid is ready
        gridRef.current?.api?.sizeColumnsToFit();
      }, 10),
    [gridRef],
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
        if (e.data.type === "folder" && e.data.url) {
          const url = e.data.url;
          setTimeout(() => {
            if (openInNewWindow) {
              window.open(url, "_blank");
            } else {
              window.location.hash = `#${url}`;
            }
          }, 10);
        } else {
          const logFile = e.data.logFile;
          const sampleId = e.data.sampleId;
          const epoch = e.data.epoch;
          setTimeout(() => {
            navigateToSampleDetail(logFile, sampleId, epoch, openInNewWindow);
          }, 10);
        }
      }
    },
    [navigateToSampleDetail, gridRef],
  );

  const handleOpenRow = useCallback(
    (rowNode: IRowNode<SampleRow>, e: KeyboardEvent) => {
      const openInNewWindow = e.metaKey || e.ctrlKey || e.shiftKey;
      if (rowNode.data?.type === "folder" && rowNode.data.url) {
        if (openInNewWindow) {
          window.open(rowNode.data.url, "_blank");
        } else {
          window.location.hash = `#${rowNode.data.url}`;
        }
        return;
      }

      if (rowNode.data) {
        navigateToSampleDetail(
          rowNode.data.logFile,
          rowNode.data.sampleId,
          rowNode.data.epoch,
          openInNewWindow,
        );
      }
    },
    [navigateToSampleDetail],
  );

  const handleKeyDown = useMemo(
    () =>
      createGridKeyboardHandler<SampleRow>({
        gridRef,
        onOpenRow: handleOpenRow,
      }),
    [gridRef, handleOpenRow],
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
    type?: string,
  ) => {
    if (type === "folder") {
      return `folder-${logFile}`.replace(/\s+/g, "_");
    }
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
              params.data.type,
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
              const gridCurrentSamples = gridDisplayedSamples(
                gridRef.current.api,
              );
              setFilteredSampleCount(gridCurrentSamples.length);
              setDisplayedSamples(gridCurrentSamples);
            }
          }}
          onRowClicked={handleRowClick}
          onFilterChanged={() => {
            if (gridRef.current?.api) {
              const newDisplayedSamples = gridDisplayedSamples(
                gridRef.current.api,
              );
              setFilteredSampleCount(newDisplayedSamples.length);
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
    if (node?.data && node.data.type !== "folder") {
      displayedSamples.push({
        logFile: node.data.logFile,
        sampleId: node.data.sampleId,
        epoch: node.data.epoch,
      });
    }
  }
  return displayedSamples;
};
