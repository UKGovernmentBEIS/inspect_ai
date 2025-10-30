import type {
  ColDef,
  RowClickedEvent,
  RowSelectedEvent,
  StateUpdatedEvent,
} from "ag-grid-community";
import {
  AllCommunityModule,
  ModuleRegistry,
  themeBalham,
} from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { FC, useCallback, useMemo, useRef } from "react";
import { Input, Score } from "../../../@types/log";
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
}

// Flattened row data for the grid
interface SampleRow {
  logFile: string;
  task: string;
  model: string;
  status: string;
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

// Helper to extract score value
const getScoreValue = (score: Score | null | undefined): any => {
  if (score === null || score === undefined) return "";
  if (typeof score === "object" && "value" in score) {
    const value = score.value;
    if (Array.isArray(value)) {
      return value.join(", ");
    }
    return value ?? "";
  }
  return score;
};

// Helper to format logFile path to show only relative path
const formatLogFilePath = (logFile: string): string => {
  return filename(logFile);
};

export const SamplesGrid: FC<SamplesGridProps> = ({ samplesPath }) => {
  const logDetails = useStore((state) => state.logs.logDetails);
  const gridState = useStore((state) => state.logs.samplesListState.gridState);
  const setGridState = useStore((state) => state.logsActions.setGridState);
  const { navigateToSampleDetail } = useSamplesGridNavigation();
  const logDir = useStore((state) => state.logs.logDir);
  const setFilteredSampleCount = useStore(
    (state) => state.logActions.setFilteredSampleCount,
  );

  const gridRef = useRef<AgGridReact>(null);

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
          status: details.status || "",
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
            row[`score_${scoreName}`] = getScoreValue(score);
          });
        }

        rows.push(row);
      });
    });

    return rows;
  }, [filteredLogDetails]);

  // Detect all unique score names across all samples
  const scoreNames = useMemo(() => {
    const names = new Set<string>();
    Object.values(filteredLogDetails).forEach((details) => {
      details.sampleSummaries.forEach((sample) => {
        if (sample.scores) {
          Object.keys(sample.scores).forEach((name) => names.add(name));
        }
      });
    });
    return Array.from(names).sort();
  }, [filteredLogDetails]);

  // Check if any sample has error, limit, or retries
  const hasError = useMemo(() => data.some((row) => row.error), [data]);
  const hasLimit = useMemo(() => data.some((row) => row.limit), [data]);
  const hasRetries = useMemo(() => data.some((row) => row.retries), [data]);

  // Create column definitions
  const columnDefs = useMemo((): ColDef<SampleRow>[] => {
    const baseColumns: ColDef<SampleRow>[] = [
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
        filter: true,
        resizable: true,
      },
      {
        field: "logFile",
        headerName: "Log File",
        initialWidth: 200,
        minWidth: 150,
        sortable: true,
        filter: true,
        resizable: true,
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
    const scoreColumns: ColDef<SampleRow>[] = scoreNames.map((scoreName) => ({
      field: `score_${scoreName}`,
      headerName: scoreName,
      initialWidth: 100,
      minWidth: 100,
      sortable: true,
      filter: true,
      resizable: true,
      valueFormatter: (params) => {
        const value = params.value;
        if (value === "" || value === null || value === undefined) return "";
        if (typeof value === "number") return value.toFixed(3);
        return String(value);
      },
    }));

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
  }, [scoreNames, hasError, hasLimit, hasRetries]);

  // Handle row selection
  const onRowSelected = useCallback((event: RowSelectedEvent<SampleRow>) => {
    if (event.node.isSelected() && event.data) {
      console.log(
        `Selected: Log File="${event.data.logFile}", Sample ID="${event.data.sampleId}", Epoch=${event.data.epoch}`,
      );
    }
  }, []);

  const resizeGridColumns = useCallback(
    debounce(() => {
      // Trigger column sizing after grid is ready
      gridRef.current?.api?.sizeColumnsToFit();
    }, 10),
    [],
  );

  return (
    <div className={styles.gridWrapper}>
      <div
        style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }}
      >
        <AgGridReact<SampleRow>
          ref={gridRef}
          rowData={data}
          columnDefs={columnDefs}
          defaultColDef={{
            sortable: true,
            filter: true,
            resizable: true,
          }}
          autoSizeStrategy={{ type: "fitGridWidth" }}
          headerHeight={25}
          rowSelection="single"
          onRowSelected={onRowSelected}
          onGridColumnsChanged={resizeGridColumns}
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
          onRowClicked={(e: RowClickedEvent<SampleRow>) => {
            if (e.data) {
              navigateToSampleDetail(
                e.data.logFile,
                e.data.sampleId,
                e.data.epoch,
              );
            }
          }}
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
