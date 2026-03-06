import {
  ColDef,
  ICellRendererParams,
  ValueFormatterParams,
  ValueGetterParams,
} from "ag-grid-community";
import { useEffect, useMemo } from "react";
import { LogDetails } from "../../../client/api/types";
import { useStore } from "../../../state/store";
import { filename } from "../../../utils/path";
import { comparators } from "../../shared/gridComparators";
import { getFieldKey } from "../../shared/gridUtils";
import styles from "../../shared/gridCells.module.css";
import { SampleRow } from "./types";
import { formatDateTime } from "../../../utils/format";

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
    (state) => state.logsActions.setSamplesColumnVisibility,
  );

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

  // Create column definitions for selector and grid
  const allColumns = useMemo((): ColDef<SampleRow>[] => {
    const baseColumns: ColDef<SampleRow>[] = [
      {
        headerName: "#",
        initialWidth: 80,
        minWidth: 50,
        maxWidth: 80,
        sortable: false,
        filter: false,
        resizable: false,
        pinned: "left",
        cellRenderer: (params: ICellRendererParams<SampleRow>) => {
          if (params.data?.displayIndex !== undefined) {
            return (
              <div className={styles.numberCell}>
                {params.data.displayIndex}
              </div>
            );
          }
          return "";
        },
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
        valueGetter: (params: ValueGetterParams<SampleRow>) =>
          String(params.data?.sampleId ?? ""),
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
        comparator: comparators.number,
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
        valueFormatter: (params: ValueFormatterParams<SampleRow>) =>
          filename(params.value),
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
          valueFormatter: (params: ValueFormatterParams<SampleRow>) => {
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
          comparator: (valA, valB) => {
            if (typeof valA === "number" && typeof valB === "number") {
              return valA - valB;
            }
            return String(valA || "").localeCompare(String(valB || ""));
          },
        };
      },
    );

    // Add optional columns (all for selector, hide unselected in grid)
    const optionalColumns: ColDef<SampleRow>[] = [
      {
        field: "created",
        headerName: "Created",
        initialWidth: 130,
        minWidth: 80,
        maxWidth: 140,
        sortable: true,
        filter: true,
        resizable: true,
        cellDataType: "date",
        filterValueGetter: (params: ValueGetterParams<SampleRow>) => {
          if (!params.data?.created) return undefined;
          const d = new Date(params.data.created);
          return new Date(d.getFullYear(), d.getMonth(), d.getDate());
        },
        valueFormatter: (params: ValueFormatterParams<SampleRow>) =>
          formatDateTime(new Date(params.value)),
      },
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
        comparator: comparators.number,
      },
    ];

    return [...baseColumns, ...scoreColumns, ...optionalColumns];
  }, [scoreMap]);

  const columns = useMemo((): ColDef<SampleRow>[] => {
    const columnsWithVisibility = allColumns.map((col: ColDef<SampleRow>) => {
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
