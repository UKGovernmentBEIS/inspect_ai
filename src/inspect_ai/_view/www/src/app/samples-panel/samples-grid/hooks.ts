import { ColDef } from "ag-grid-community";
import { useEffect, useMemo } from "react";
import { useStore } from "../../../state/store";
import { LogDetails } from "../../../client/api/types";
import { filename } from "../../../utils/path";
import { SampleRow } from "./types";

export const getFieldKey = (col: ColDef<SampleRow>): string => {
  return col.field || col.headerName || "?";
};

export const useSampleColumns = (logDetails: Record<string, LogDetails>) => {
  const optionalColumnsHaveAnyData: Record<string, boolean> = useMemo(() => {
    let error = false;
    let limit = false;
    let retries = false;
    outerLoop: for (const details of Object.values(logDetails)) {
      for (const sample of details.sampleSummaries) {
        if (sample.error) error = true;
        if (sample.limit) limit = true;
        if (sample.retries) retries = true;
        if (error && limit && retries) break outerLoop;
      }
    }
    return { error, limit, retries };
  }, [logDetails]);
  const columnVisibility = useStore(
    (state) => state.logs.samplesListState.columnVisibility,
  );
  const setColumnVisibility = useStore(
    (state) => state.logsActions.setColumnVisibility,
  );
  useEffect(() => {
    // if optional columns are not set manually, set their visibility based on the data
    const { error, limit, retries } = optionalColumnsHaveAnyData;
    if (
      "error" in columnVisibility ||
      "limit" in columnVisibility ||
      "retries" in columnVisibility ||
      (!error && !limit && !retries)
    ) {
      return;
    }
    const newVisibility = { ...columnVisibility };
    if (error && !("error" in columnVisibility)) newVisibility.error = true;
    if (limit && !("limit" in columnVisibility)) newVisibility.limit = true;
    if (retries && !("retries" in columnVisibility))
      newVisibility.retries = true;
    setColumnVisibility(newVisibility);
  }, [optionalColumnsHaveAnyData, columnVisibility, setColumnVisibility]);

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

  // Create column definitions for selector and grid
  const allColumns = useMemo((): ColDef<SampleRow>[] => {
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

    // Add optional columns (all for selector, hide unselected in grid)
    const optionalColumns: ColDef<SampleRow>[] = [
      {
        field: "error",
        headerName: "Error",
        initialWidth: 150,
        minWidth: 100,
        sortable: true,
        filter: true,
        resizable: true,
        cellStyle: { overflow: "hidden", textOverflow: "ellipsis" },
      },
      {
        field: "limit",
        headerName: "Limit",
        initialWidth: 100,
        minWidth: 80,
        sortable: true,
        filter: true,
        resizable: true,
      },
      {
        field: "retries",
        headerName: "Retries",
        initialWidth: 80,
        minWidth: 60,
        sortable: true,
        filter: true,
        resizable: true,
      },
    ];

    return [...baseColumns, ...scoreColumns, ...optionalColumns];
  }, [scoreMap]);

  const columns = useMemo((): ColDef<SampleRow>[] => {
    const columnsWithVisibility = allColumns.map((col) => {
      const field = getFieldKey(col);
      // Default to visible if not explicitly unselected and not optional
      const isVisible =
        (columnVisibility[field] ?? optionalColumnsHaveAnyData[field]) !==
        false;
      return {
        ...col,
        hide: !isVisible,
      };
    });

    return columnsWithVisibility;
  }, [allColumns, columnVisibility, optionalColumnsHaveAnyData]);

  return {
    columns,
    setColumnVisibility,
  };
};
