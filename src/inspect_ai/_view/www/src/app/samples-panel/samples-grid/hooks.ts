import { ColDef } from "ag-grid-community";
import { useMemo } from "react";
import { LogDetails } from "../../../client/api/types";
import { filename } from "../../../utils/path";
import { SampleRow } from "./types";

export const useSampleColumns = (
  data: SampleRow[],
  logDetails: Record<string, LogDetails>,
) => {
  // Check if any sample has error, limit, or retries
  const hasError = useMemo(() => data.some((row) => row.error), [data]);
  const hasLimit = useMemo(() => data.some((row) => row.limit), [data]);
  const hasRetries = useMemo(() => data.some((row) => row.retries), [data]);

  // Detect all unique score names across all samples
  const scoreMap = useMemo(() => {
    const scoreTypes: Record<string, string> = {};

    for (const details of Object.values(logDetails)) {
      for (const sample of details.sampleSummaries) {
        if (sample.scores) {
          for (const [name, score] of Object.entries(sample.scores)) {
            scoreTypes[name] = typeof score.value;
          }
        }
      }
    }
    return scoreTypes;
  }, [logDetails]);

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
        filter: true,
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
        valueFormatter: (params) => filename(params.value),
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
  return columns;
};
