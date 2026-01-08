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
import { useSamplesGridNavigation } from "../../routing/sampleNavigation";
import { DisplayedSample } from "../../types";
import "../../shared/agGrid";
import { createGridKeyboardHandler } from "../../shared/gridKeyboardNavigation";
import { createGridColumnResizer } from "../../shared/gridUtils";
import styles from "../../shared/gridCells.module.css";
import { SampleRow } from "./types";

// Sample Grid Props
interface SamplesGridProps {
  items: SampleRow[];
  samplesPath?: string;
  gridRef?: RefObject<AgGridReact<SampleRow> | null>;
  columns: ColDef<SampleRow>[];
}

// Sample Grid
export const SamplesGrid: FC<SamplesGridProps> = ({
  items,
  samplesPath,
  gridRef: externalGridRef,
  columns,
}) => {
  const gridState = useStore((state) => state.logs.samplesListState.gridState);
  const setGridState = useStore((state) => state.logsActions.setGridState);
  const { navigateToSampleDetail } = useSamplesGridNavigation();
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

  useEffect(() => {
    gridContainerRef.current?.focus();
  }, []);

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

  const handleOpenRow = useCallback(
    (rowNode: IRowNode<SampleRow>, e: KeyboardEvent) => {
      const openInNewWindow = e.metaKey || e.ctrlKey || e.shiftKey;
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

  const resizeGridColumns = useRef(createGridColumnResizer(gridRef)).current;

  // Resize grid columns when columns prop changes (e.g., when columns are hidden/unhidden)
  useEffect(() => {
    resizeGridColumns();
  }, [columns, resizeGridColumns]);

  return (
    <div className={styles.gridWrapper}>
      <div ref={gridContainerRef} className={styles.gridContainer} tabIndex={0}>
        <AgGridReact<SampleRow>
          ref={gridRef}
          rowData={items}
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
          loading={items.length === 0 && (loading > 0 || syncing)}
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
