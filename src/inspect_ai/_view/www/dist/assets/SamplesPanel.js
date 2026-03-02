import { u as useStore, j as jsxRuntimeExports, f as filename, J as useSamplesRouteParams, d as join, I as samplesUrl, A as ApplicationIcons } from "./index.js";
import { a as formatDateTime, b as useLogs, d as useLogsWithretried, t as inputString, A as ApplicationNavbar, Q as ActivityBar, c as clsx } from "./ApplicationNavbar.js";
import { b as reactExports, A as AgGridReact, t as themeBalham } from "./vendor-grid.js";
import { a as comparators, g as getFieldKey, s as styles$1, u as useClientEvents, b as createGridColumnResizer, N as NavbarButton, V as ViewSegmentedControl, F as FlowButton, C as ColumnSelectorPopover, L as LogListFooter, P as ProgressBar } from "./LogListFooter.js";
import { u as useFlowServerData } from "./hooks.js";
import { b as useSamplesGridNavigation } from "./sampleNavigation.js";
import { c as createGridKeyboardHandler } from "./gridKeyboardNavigation.js";
import "./vendor-prism.js";
const useSampleColumns = (logDetails) => {
  const optionalColumnsHaveAnyData = reactExports.useMemo(() => {
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
    (state) => state.logs.samplesListState.columnVisibility
  );
  const setColumnVisibility = useStore(
    (state) => state.logsActions.setSamplesColumnVisibility
  );
  const scoreMap = reactExports.useMemo(() => {
    const scoreTypes = {};
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
  reactExports.useEffect(() => {
    const { error, limit, retries } = optionalColumnsHaveAnyData;
    if ("error" in columnVisibility || "limit" in columnVisibility || "retries" in columnVisibility || !error && !limit && !retries) {
      return;
    }
    const newVisibility = { ...columnVisibility };
    if (error && !("error" in columnVisibility)) newVisibility.error = true;
    if (limit && !("limit" in columnVisibility)) newVisibility.limit = true;
    if (retries && !("retries" in columnVisibility))
      newVisibility.retries = true;
    setColumnVisibility(newVisibility);
  }, [optionalColumnsHaveAnyData, columnVisibility, setColumnVisibility]);
  const allColumns = reactExports.useMemo(() => {
    const baseColumns = [
      {
        headerName: "#",
        initialWidth: 80,
        minWidth: 50,
        maxWidth: 80,
        sortable: false,
        filter: false,
        resizable: false,
        pinned: "left",
        cellRenderer: (params) => {
          if (params.data?.displayIndex !== void 0) {
            return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$1.numberCell, children: params.data.displayIndex });
          }
          return "";
        }
      },
      {
        field: "task",
        headerName: "Task",
        initialWidth: 150,
        minWidth: 100,
        sortable: true,
        filter: true,
        resizable: true
      },
      {
        field: "model",
        headerName: "Model",
        initialWidth: 150,
        minWidth: 100,
        sortable: true,
        filter: true,
        resizable: true
      },
      {
        field: "sampleId",
        headerName: "Sample ID",
        initialWidth: 120,
        minWidth: 100,
        sortable: true,
        filter: true,
        resizable: true,
        valueGetter: (params) => String(params.data?.sampleId ?? "")
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
        comparator: comparators.number
      },
      {
        field: "input",
        headerName: "Input",
        initialWidth: 250,
        minWidth: 150,
        sortable: true,
        filter: true,
        resizable: true,
        cellStyle: { overflow: "hidden", textOverflow: "ellipsis" }
      },
      {
        field: "status",
        headerName: "Status",
        initialWidth: 100,
        minWidth: 80,
        sortable: true,
        resizable: true,
        filter: true
      },
      {
        field: "logFile",
        headerName: "Log File",
        initialWidth: 200,
        minWidth: 150,
        sortable: true,
        filter: true,
        resizable: true,
        valueFormatter: (params) => filename(params.value)
      },
      {
        field: "target",
        headerName: "Target",
        initialWidth: 150,
        minWidth: 100,
        sortable: true,
        filter: true,
        resizable: true,
        cellStyle: { overflow: "hidden", textOverflow: "ellipsis" }
      }
    ];
    const scoreColumns = Object.keys(scoreMap).map(
      (scoreName) => {
        const scoreType = scoreMap[scoreName];
        return {
          field: `score_${scoreName}`,
          headerName: scoreName,
          initialWidth: 100,
          minWidth: 100,
          sortable: true,
          filter: scoreType === "number" ? "agNumberColumnFilter" : "agTextColumnFilter",
          resizable: true,
          valueFormatter: (params) => {
            const value = params.value;
            if (value === "" || value === null || value === void 0) {
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
          }
        };
      }
    );
    const optionalColumns = [
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
        filterValueGetter: (params) => {
          if (!params.data?.created) return void 0;
          const d = new Date(params.data.created);
          return new Date(d.getFullYear(), d.getMonth(), d.getDate());
        },
        valueFormatter: (params) => formatDateTime(new Date(params.value))
      },
      {
        field: "error",
        headerName: "Error",
        initialWidth: 150,
        minWidth: 100,
        sortable: true,
        filter: true,
        resizable: true,
        cellStyle: { overflow: "hidden", textOverflow: "ellipsis" }
      },
      {
        field: "limit",
        headerName: "Limit",
        initialWidth: 100,
        minWidth: 80,
        sortable: true,
        filter: true,
        resizable: true
      },
      {
        field: "retries",
        headerName: "Retries",
        initialWidth: 80,
        minWidth: 60,
        sortable: true,
        filter: true,
        resizable: true,
        comparator: comparators.number
      }
    ];
    return [...baseColumns, ...scoreColumns, ...optionalColumns];
  }, [scoreMap]);
  const columns = reactExports.useMemo(() => {
    const columnsWithVisibility = allColumns.map((col) => {
      const field = getFieldKey(col);
      const isVisible = (columnVisibility[field] ?? optionalColumnsHaveAnyData[field]) !== false;
      return {
        ...col,
        hide: !isVisible
      };
    });
    return columnsWithVisibility;
  }, [allColumns, columnVisibility, optionalColumnsHaveAnyData]);
  return {
    columns,
    setColumnVisibility
  };
};
const SamplesGrid = ({
  items,
  samplesPath,
  gridRef: externalGridRef,
  columns
}) => {
  const gridState = useStore((state) => state.logs.samplesListState.gridState);
  const setGridState = useStore((state) => state.logsActions.setGridState);
  const { navigateToSampleDetail } = useSamplesGridNavigation();
  const setFilteredSampleCount = useStore(
    (state) => state.logActions.setFilteredSampleCount
  );
  const setDisplayedSamples = useStore(
    (state) => state.logsActions.setDisplayedSamples
  );
  const clearDisplayedSamples = useStore(
    (state) => state.logsActions.clearDisplayedSamples
  );
  const clearSelectedSample = useStore(
    (state) => state.sampleActions.clearSelectedSample
  );
  const previousSamplesPath = useStore(
    (state) => state.logs.samplesListState.previousSamplesPath
  );
  const setPreviousSamplesPath = useStore(
    (state) => state.logsActions.setPreviousSamplesPath
  );
  const loading = useStore((state) => state.app.status.loading);
  const syncing = useStore((state) => state.app.status.syncing);
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  const selectedSampleHandle = useStore(
    (state) => state.log.selectedSampleHandle
  );
  const internalGridRef = reactExports.useRef(null);
  const gridRef = externalGridRef || internalGridRef;
  const gridContainerRef = reactExports.useRef(null);
  const { startPolling, stopPolling } = useClientEvents();
  reactExports.useEffect(() => {
    startPolling([]);
    return () => {
      stopPolling();
    };
  }, [startPolling, stopPolling]);
  const initialGridState = reactExports.useMemo(() => {
    if (previousSamplesPath !== void 0 && previousSamplesPath !== samplesPath) {
      clearDisplayedSamples();
      const result = { ...gridState };
      delete result?.filter;
      return result;
    } else {
      return gridState;
    }
  }, [previousSamplesPath, samplesPath, clearDisplayedSamples, gridState]);
  reactExports.useEffect(() => {
    if (samplesPath !== previousSamplesPath) {
      setPreviousSamplesPath(samplesPath);
    }
  }, [samplesPath, previousSamplesPath, setPreviousSamplesPath]);
  reactExports.useEffect(() => {
    gridContainerRef.current?.focus();
  }, []);
  const handleRowClick = reactExports.useCallback(
    (e) => {
      if (e.data && e.node && gridRef.current?.api) {
        gridRef.current.api.deselectAll();
        e.node.setSelected(true);
        const mouseEvent = e.event;
        const openInNewWindow = mouseEvent?.metaKey || mouseEvent?.ctrlKey || mouseEvent?.shiftKey || mouseEvent?.button === 1;
        const logFile = e.data.logFile;
        const sampleId = e.data.sampleId;
        const epoch = e.data.epoch;
        setTimeout(() => {
          navigateToSampleDetail(logFile, sampleId, epoch, openInNewWindow);
        }, 10);
      }
    },
    [navigateToSampleDetail, gridRef]
  );
  const handleOpenRow = reactExports.useCallback(
    (rowNode, e) => {
      const openInNewWindow = e.metaKey || e.ctrlKey || e.shiftKey;
      if (rowNode.data) {
        navigateToSampleDetail(
          rowNode.data.logFile,
          rowNode.data.sampleId,
          rowNode.data.epoch,
          openInNewWindow
        );
      }
    },
    [navigateToSampleDetail]
  );
  const handleKeyDown = reactExports.useMemo(
    () => createGridKeyboardHandler({
      gridRef,
      onOpenRow: handleOpenRow
    }),
    [gridRef, handleOpenRow]
  );
  reactExports.useEffect(() => {
    const gridElement = gridContainerRef.current;
    if (!gridElement) return;
    gridElement.addEventListener("keydown", handleKeyDown);
    return () => {
      gridElement.removeEventListener("keydown", handleKeyDown);
    };
  }, [handleKeyDown]);
  const sampleRowId = (logFile, sampleId, epoch) => {
    return `${logFile}-${sampleId}-${epoch}`.replace(/\s+/g, "_");
  };
  const selectCurrentSample = reactExports.useCallback(() => {
    if (!gridRef.current?.api || !selectedSampleHandle || !selectedLogFile) {
      return;
    }
    const rowId = sampleRowId(
      selectedLogFile,
      selectedSampleHandle.id,
      selectedSampleHandle.epoch
    );
    const node = gridRef.current.api.getRowNode(rowId);
    if (node) {
      gridRef.current.api.deselectAll();
      node.setSelected(true);
      gridRef.current.api.ensureNodeVisible(node, "middle");
    }
  }, [gridRef, selectedSampleHandle, selectedLogFile]);
  reactExports.useEffect(() => {
    selectCurrentSample();
  }, [selectedSampleHandle, selectedLogFile, selectCurrentSample]);
  const maxColCount = reactExports.useRef(0);
  const resizeGridColumns = reactExports.useRef(createGridColumnResizer(gridRef)).current;
  reactExports.useEffect(() => {
    resizeGridColumns();
  }, [columns, resizeGridColumns]);
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$1.gridWrapper, children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { ref: gridContainerRef, className: styles$1.gridContainer, tabIndex: 0, children: /* @__PURE__ */ jsxRuntimeExports.jsx(
    AgGridReact,
    {
      ref: gridRef,
      rowData: items,
      animateRows: false,
      columnDefs: columns,
      defaultColDef: {
        sortable: true,
        filter: true,
        resizable: true
      },
      tooltipShowDelay: 300,
      autoSizeStrategy: { type: "fitGridWidth" },
      headerHeight: 25,
      rowSelection: { mode: "singleRow", checkboxes: false },
      getRowId: (params) => sampleRowId(
        params.data.logFile,
        params.data.sampleId,
        params.data.epoch
      ),
      onGridColumnsChanged: (e) => {
        const cols = e.api.getColumnDefs();
        if (cols && cols?.length > maxColCount.current) {
          maxColCount.current = cols.length;
          resizeGridColumns();
        }
      },
      onGridSizeChanged: resizeGridColumns,
      theme: themeBalham,
      enableCellTextSelection: true,
      initialState: initialGridState,
      suppressCellFocus: true,
      onStateUpdated: (e) => {
        setGridState(e.state);
        if (gridRef.current?.api) {
          const gridCurrentSamples = gridDisplayedSamples(
            gridRef.current.api
          );
          setFilteredSampleCount(gridCurrentSamples.length);
          setDisplayedSamples(gridCurrentSamples);
        }
      },
      onRowClicked: handleRowClick,
      onFilterChanged: () => {
        if (gridRef.current?.api) {
          const newDisplayedSamples = gridDisplayedSamples(
            gridRef.current.api
          );
          setFilteredSampleCount(newDisplayedSamples.length);
          setDisplayedSamples(newDisplayedSamples);
        }
      },
      onFirstDataRendered: () => {
        selectCurrentSample();
        clearSelectedSample();
      },
      loading: items.length === 0 && (loading > 0 || syncing)
    }
  ) }) });
};
const gridDisplayedSamples = (gridApi) => {
  const displayedSamples = [];
  const displayedRowCount = gridApi.getDisplayedRowCount();
  for (let i = 0; i < displayedRowCount; i++) {
    const node = gridApi.getDisplayedRowAtIndex(i);
    if (node?.data) {
      displayedSamples.push({
        logFile: node.data.logFile,
        sampleId: node.data.sampleId,
        epoch: node.data.epoch
      });
    }
  }
  return displayedSamples;
};
const panel = "_panel_18nhs_1";
const list = "_list_18nhs_8";
const styles = {
  panel,
  list
};
const SamplesPanel = () => {
  const { samplesPath } = useSamplesRouteParams();
  const { loadLogs } = useLogs();
  const logDir = useStore((state) => state.logs.logDir);
  const loading = useStore((state) => state.app.status.loading);
  const syncing = useStore((state) => state.app.status.syncing);
  const showRetriedLogs = useStore((state) => state.logs.showRetriedLogs);
  const setShowRetriedLogs = useStore(
    (state) => state.logsActions.setShowRetriedLogs
  );
  const filteredSamplesCount = useStore(
    (state) => state.log.filteredSampleCount
  );
  const setFilteredSampleCount = useStore(
    (state) => state.logActions.setFilteredSampleCount
  );
  const gridRef = reactExports.useRef(null);
  const [showColumnSelector, setShowColumnSelector] = reactExports.useState(false);
  const columnButtonRef = reactExports.useRef(null);
  const logDetails = useStore((state) => state.logs.logDetails);
  const { columns, setColumnVisibility } = useSampleColumns(logDetails);
  const handleColumnVisibilityChange = reactExports.useCallback(
    (newVisibility) => {
      if (gridRef.current?.api) {
        const currentFilterModel = gridRef.current.api.getFilterModel() || {};
        let filtersRemoved = false;
        const newFilterModel = {};
        for (const [field, filter] of Object.entries(currentFilterModel)) {
          if (newVisibility[field] === false) {
            filtersRemoved = true;
          } else {
            newFilterModel[field] = filter;
          }
        }
        if (filtersRemoved) {
          gridRef.current.api.setFilterModel(newFilterModel);
        }
      }
      setColumnVisibility(newVisibility);
    },
    [setColumnVisibility]
  );
  const handleResetFilters = () => {
    if (gridRef.current?.api) {
      gridRef.current.api.setFilterModel(null);
    }
  };
  useFlowServerData(samplesPath || "");
  const flowData = useStore((state) => state.logs.flow);
  const currentDir = join(samplesPath || "", logDir);
  const evalSet = useStore((state) => state.logs.evalSet);
  const logFiles = useLogsWithretried();
  const logPreviews = useStore((state) => state.logs.logPreviews);
  const currentDirLogFiles = reactExports.useMemo(() => {
    const files = [];
    for (const logFile of logFiles) {
      const inCurrentDir = logFile.name.startsWith(currentDir);
      const skipped = !showRetriedLogs && logFile.retried;
      if (inCurrentDir && !skipped) {
        files.push(logFile);
      }
    }
    return files;
  }, [currentDir, logFiles, showRetriedLogs]);
  const totalTaskCount = reactExports.useMemo(() => {
    const currentDirTaskIds = new Set(currentDirLogFiles.map((f) => f.task_id));
    let count = currentDirLogFiles.length;
    for (const task of evalSet?.tasks || []) {
      if (!currentDirTaskIds.has(task.task_id)) {
        count++;
      }
    }
    return count;
  }, [currentDirLogFiles, evalSet]);
  const completedTaskCount = reactExports.useMemo(() => {
    let count = 0;
    for (const logFile of currentDirLogFiles) {
      const preview = logPreviews[logFile.name];
      if (preview && preview.status !== "started") {
        count++;
      }
    }
    return count;
  }, [logPreviews, currentDirLogFiles]);
  reactExports.useEffect(() => {
    loadLogs(samplesPath);
  }, [loadLogs, samplesPath]);
  const logDetailsInPath = reactExports.useMemo(() => {
    if (!samplesPath) {
      return logDetails;
    }
    const samplesPathAbs = join(samplesPath, logDir);
    return Object.entries(logDetails).reduce(
      (acc, [logFile, details]) => {
        if (logFile.startsWith(samplesPathAbs)) {
          acc[logFile] = details;
        }
        return acc;
      },
      {}
    );
  }, [logDetails, logDir, samplesPath]);
  const [sampleRows, hasRetriedLogs] = reactExports.useMemo(() => {
    const allRows = [];
    let displayIndex = 1;
    let anyLogInCurrentDirCouldBeSkipped = false;
    const logInCurrentDirByName = currentDirLogFiles.reduce(
      (acc, log) => {
        if (log.retried) {
          anyLogInCurrentDirCouldBeSkipped = true;
        }
        acc[log.name] = log;
        return acc;
      },
      {}
    );
    Object.entries(logDetailsInPath).forEach(([logFile, logDetail]) => {
      logDetail.sampleSummaries.forEach((sampleSummary) => {
        const row = {
          logFile,
          created: logDetail.eval.created,
          task: logDetail.eval.task || "",
          model: logDetail.eval.model || "",
          status: logDetail.status,
          sampleId: sampleSummary.id,
          epoch: sampleSummary.epoch,
          input: inputString(sampleSummary.input).join("\n"),
          target: Array.isArray(sampleSummary.target) ? sampleSummary.target.join(", ") : sampleSummary.target,
          error: sampleSummary.error,
          limit: sampleSummary.limit,
          retries: sampleSummary.retries,
          completed: sampleSummary.completed || false,
          displayIndex: displayIndex++
        };
        if (sampleSummary.scores) {
          Object.entries(sampleSummary.scores).forEach(([scoreName, score]) => {
            row[`score_${scoreName}`] = score.value;
          });
        }
        allRows.push(row);
      });
    });
    const _sampleRows = allRows.filter(
      (row) => row.logFile in logInCurrentDirByName
    );
    const _hasRetriedLogs = _sampleRows.length < allRows.length || anyLogInCurrentDirCouldBeSkipped;
    return [_sampleRows, _hasRetriedLogs];
  }, [logDetailsInPath, currentDirLogFiles]);
  const filterModel = gridRef.current?.api?.getFilterModel() || {};
  const filteredFields = Object.keys(filterModel);
  const hasFilter = filteredFields.length > 0;
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles.panel), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs(ApplicationNavbar, { currentPath: samplesPath, fnNavigationUrl: samplesUrl, children: [
      hasFilter && /* @__PURE__ */ jsxRuntimeExports.jsx(
        NavbarButton,
        {
          label: "Reset Filters",
          icon: ApplicationIcons.filter,
          onClick: handleResetFilters
        },
        "reset-filters"
      ),
      hasRetriedLogs && /* @__PURE__ */ jsxRuntimeExports.jsx(
        NavbarButton,
        {
          label: "Show Retried Logs",
          icon: showRetriedLogs ? ApplicationIcons.toggle.on : ApplicationIcons.toggle.off,
          latched: showRetriedLogs,
          onClick: () => {
            setShowRetriedLogs(!showRetriedLogs);
            setTimeout(() => {
              if (gridRef.current) {
                setFilteredSampleCount(
                  gridRef.current.api.getDisplayedRowCount()
                );
              }
            }, 10);
          }
        },
        "show-retried"
      ),
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        NavbarButton,
        {
          ref: columnButtonRef,
          label: "Choose Columns",
          icon: ApplicationIcons.checkbox.checked,
          onClick: (e) => {
            e.stopPropagation();
            setShowColumnSelector((prev) => !prev);
          }
        },
        "choose-columns"
      ),
      /* @__PURE__ */ jsxRuntimeExports.jsx(ViewSegmentedControl, { selectedSegment: "samples" }),
      flowData && /* @__PURE__ */ jsxRuntimeExports.jsx(FlowButton, {})
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      ColumnSelectorPopover,
      {
        showing: showColumnSelector,
        setShowing: setShowColumnSelector,
        columns,
        onVisibilityChange: handleColumnVisibilityChange,
        positionEl: columnButtonRef.current,
        filteredFields
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsx(ActivityBar, { animating: !!loading }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles.list, "text-size-smaller"), children: /* @__PURE__ */ jsxRuntimeExports.jsx(
      SamplesGrid,
      {
        items: sampleRows,
        samplesPath,
        gridRef,
        columns
      }
    ) }),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      LogListFooter,
      {
        itemCount: filteredSamplesCount ?? 0,
        itemCountLabel: filteredSamplesCount === 1 ? "sample" : "samples",
        progressText: syncing ? `Syncing${filteredSamplesCount ? ` (${filteredSamplesCount.toLocaleString()} samples)` : ""}` : void 0,
        progressBar: totalTaskCount !== completedTaskCount ? /* @__PURE__ */ jsxRuntimeExports.jsx(
          ProgressBar,
          {
            min: 0,
            max: totalTaskCount,
            value: completedTaskCount,
            width: "100px",
            label: "tasks"
          }
        ) : void 0
      }
    )
  ] });
};
export {
  SamplesPanel
};
//# sourceMappingURL=SamplesPanel.js.map
