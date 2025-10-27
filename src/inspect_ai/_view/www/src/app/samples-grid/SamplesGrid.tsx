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
import { FC, useCallback, useEffect, useMemo } from "react";
import { Score } from "../../@types/log";
import { useStore } from "../../state/store";
import { filename } from "../../utils/path";
import { useSampleNavigation } from "../routing/sampleNavigation";
import styles from "./SamplesGrid.module.css";

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

interface SamplesGridProps {}

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
const formatInput = (input: any): string => {
  if (typeof input === "string") return input;
  if (Array.isArray(input)) {
    return input
      .map((item) => {
        if (typeof item === "string") return item;
        if (item?.type === "text") return item.text;
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

export const SamplesGrid: FC<SamplesGridProps> = () => {
  const logDetails = useStore((state) => state.logs.logDetails);
  const gridState = useStore((state) => state.logs.samplesListState.gridState);
  const setGridState = useStore((state) => state.logsActions.setGridState);
  const { showSample } = useSampleNavigation();
  const setSelectedLogFile = useStore(
    (state) => state.logsActions.setSelectedLogFile,
  );

  // Debug: Log when component renders
  useEffect(() => {
    console.log(
      "SamplesGrid mounted, logDetails count:",
      Object.keys(logDetails).length,
    );
  }, []);

  useEffect(() => {
    console.log(
      "SamplesGrid logDetails updated:",
      Object.keys(logDetails).length,
    );
  }, [logDetails]);

  // Transform logDetails into flat rows
  const data = useMemo(() => {
    const rows: SampleRow[] = [];

    Object.entries(logDetails).forEach(([logFile, details]) => {
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
  }, [logDetails]);

  // Detect all unique score names across all samples
  const scoreNames = useMemo(() => {
    const names = new Set<string>();
    Object.values(logDetails).forEach((details) => {
      details.sampleSummaries.forEach((sample) => {
        if (sample.scores) {
          Object.keys(sample.scores).forEach((name) => names.add(name));
        }
      });
    });
    return Array.from(names).sort();
  }, [logDetails]);

  // Check if any sample has error, limit, or retries
  const hasError = useMemo(() => data.some((row) => row.error), [data]);
  const hasLimit = useMemo(() => data.some((row) => row.limit), [data]);
  const hasRetries = useMemo(() => data.some((row) => row.retries), [data]);
  const hasRunning = useMemo(
    () => data.some((row) => row.completed === false),
    [data],
  );

  // Create column definitions
  const columnDefs = useMemo((): ColDef<SampleRow>[] => {
    const baseColumns: ColDef<SampleRow>[] = [
      {
        field: "task",
        headerName: "Task",
        width: 150,
        minWidth: 100,
        sortable: true,
        filter: true,
        resizable: true,
      },
      {
        field: "model",
        headerName: "Model",
        width: 150,
        minWidth: 100,
        sortable: true,
        filter: true,
        resizable: true,
      },
      {
        field: "sampleId",
        headerName: "Sample ID",
        width: 120,
        minWidth: 80,
        sortable: true,
        filter: true,
        resizable: true,
      },
      {
        field: "epoch",
        headerName: "Epoch",
        width: 70,
        minWidth: 40,
        sortable: true,
        filter: true,
        resizable: true,
        cellStyle: { textAlign: "center" },
      },

      {
        field: "input",
        headerName: "Input",
        width: 250,
        minWidth: 150,
        sortable: true,
        filter: true,
        resizable: true,
        cellStyle: { overflow: "hidden", textOverflow: "ellipsis" },
      },
      {
        field: "status",
        headerName: "Status",
        width: 100,
        minWidth: 80,
        sortable: true,
        filter: true,
        resizable: true,
      },
      {
        field: "logFile",
        headerName: "Log File",
        width: 200,
        minWidth: 150,
        sortable: true,
        filter: true,
        resizable: true,
        valueFormatter: (params) => formatLogFilePath(params.value),
      },
      {
        field: "target",
        headerName: "Target",
        width: 150,
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
      width: 100,
      minWidth: 80,
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
        width: 150,
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
        width: 100,
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
        width: 80,
        minWidth: 60,
        sortable: true,
        filter: true,
        resizable: true,
      });
    }

    if (hasRunning) {
      optionalColumns.push({
        field: "completed",
        headerName: "Completed",
        width: 80,
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

  return (
    <div className={styles.gridWrapper}>
      <div
        style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }}
      >
        <AgGridReact<SampleRow>
          rowData={data}
          columnDefs={columnDefs}
          defaultColDef={{
            sortable: true,
            filter: true,
            resizable: true,
          }}
          rowSelection="single"
          onRowSelected={onRowSelected}
          theme={themeBalham}
          enableCellTextSelection={true}
          initialState={gridState}
          onStateUpdated={(e: StateUpdatedEvent<SampleRow>) => {
            setGridState(e.state);
          }}
          onRowClicked={(e: RowClickedEvent<SampleRow>) => {
            if (e.data) {
              setSelectedLogFile(e.data.logFile);
              showSample(e.data.sampleId, e.data.epoch);
            }
          }}
        />
      </div>
    </div>
  );
};
