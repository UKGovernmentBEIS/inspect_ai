import { f as filename, u as useStore, j as jsxRuntimeExports, A as ApplicationIcons, b as basename, a as useNavigate, c as useLogRouteParams, d as join, i as isInDirectory, e as directoryRelativeUrl, l as logsUrl, g as dirname } from "./index.js";
import { f as formatPrettyDecimal, c as clsx, a as formatDateTime, u as useLogsListing, b as useLogs, d as useLogsWithretried, A as ApplicationNavbar, e as useDocumentTitle } from "./ApplicationNavbar.js";
import { b as reactExports, A as AgGridReact, t as themeBalham } from "./vendor-grid.js";
import { c as createFolderFirstComparator, s as styles$2, g as getFieldKey, a as comparators, b as createGridColumnResizer, u as useClientEvents, N as NavbarButton, V as ViewSegmentedControl, F as FlowButton, C as ColumnSelectorPopover, L as LogListFooter, P as ProgressBar } from "./LogListFooter.js";
import { u as useFlowServerData } from "./hooks.js";
import { c as createGridKeyboardHandler } from "./gridKeyboardNavigation.js";
import "./vendor-prism.js";
const kLogFilePattern = /^(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}[-+]\d{2}-\d{2})_(.+)_([0-9A-Za-z]+)\.(eval|json)$/;
const parseLogFileName = (logFileName) => {
  const match = logFileName.match(kLogFilePattern);
  if (!match) {
    return {
      timestamp: void 0,
      name: filename(logFileName),
      taskId: void 0,
      extension: logFileName.endsWith(".eval") ? "eval" : "json"
    };
  }
  return {
    timestamp: new Date(Date.parse(match[1])),
    name: match[2],
    taskId: match[3],
    extension: match[4]
  };
};
const nameCell = "_nameCell_1jtud_1";
const modelCell = "_modelCell_1jtud_8";
const scoreCell = "_scoreCell_1jtud_15";
const error = "_error_1jtud_22";
const started = "_started_1jtud_26";
const success = "_success_1jtud_30";
const cancelled = "_cancelled_1jtud_34";
const statusCell = "_statusCell_1jtud_38";
const dateCell = "_dateCell_1jtud_45";
const localStyles = {
  nameCell,
  modelCell,
  scoreCell,
  error,
  started,
  success,
  cancelled,
  statusCell,
  dateCell
};
const styles$1 = { ...styles$2, ...localStyles };
const EmptyCell = () => /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: "-" });
const useLogListColumns = () => {
  const columnVisibility = useStore(
    (state) => state.logs.listing.columnVisibility
  );
  const setColumnVisibility = useStore(
    (state) => state.logsActions.setLogsColumnVisibility
  );
  const logDetails = useStore((state) => state.logs.logDetails);
  const scorerMap = reactExports.useMemo(() => {
    const scoreTypes = {};
    for (const details of Object.values(logDetails)) {
      if (details.results?.scores) {
        for (const evalScore of details.results.scores) {
          if (evalScore.metrics) {
            for (const [metricName, metric] of Object.entries(
              evalScore.metrics
            )) {
              scoreTypes[metricName] = typeof metric.value;
            }
          }
        }
      }
    }
    return scoreTypes;
  }, [logDetails]);
  reactExports.useEffect(() => {
    const scorerNames = Object.keys(scorerMap);
    if (scorerNames.length === 0) return;
    const needsUpdate = scorerNames.some(
      (name) => !(`score_${name}` in columnVisibility)
    );
    if (needsUpdate) {
      const newVisibility = { ...columnVisibility };
      for (const scorerName of scorerNames) {
        const field = `score_${scorerName}`;
        if (!(field in columnVisibility)) {
          newVisibility[field] = false;
        }
      }
      setColumnVisibility(newVisibility);
    }
  }, [scorerMap, columnVisibility, setColumnVisibility]);
  const allColumns = reactExports.useMemo(() => {
    const baseColumns = [
      {
        field: "type",
        headerName: "",
        initialWidth: 32,
        minWidth: 32,
        maxWidth: 32,
        suppressSizeToFit: true,
        sortable: true,
        filter: false,
        resizable: false,
        pinned: "left",
        cellRenderer: (params) => {
          const type = params.data?.type;
          const icon = type === "file" || type === "pending-task" ? ApplicationIcons.inspectFile : ApplicationIcons.folder;
          return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$1.iconCell, children: /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: clsx(icon) }) });
        }
      },
      {
        field: "task",
        headerName: "Task",
        initialWidth: 250,
        minWidth: 150,
        sortable: true,
        filter: true,
        resizable: true,
        valueGetter: (params) => {
          const item = params.data;
          if (!item) return "";
          if (item.type === "file") {
            return item.task || parseLogFileName(item.name).name;
          }
          return item.name;
        },
        cellRenderer: (params) => {
          const item = params.data;
          if (!item) return null;
          let value = item.name;
          if (item.type === "file") {
            value = item.task || parseLogFileName(item.name).name;
          }
          return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$1.nameCell, children: item.type === "folder" && item.url ? /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: styles$1.folder, children: value }) : /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: styles$1.taskText, children: value }) });
        }
      },
      {
        field: "model",
        headerName: "Model",
        initialWidth: 300,
        minWidth: 100,
        maxWidth: 400,
        sortable: true,
        filter: true,
        resizable: true,
        cellRenderer: (params) => {
          const item = params.data;
          if (!item) return null;
          if (item.model) {
            return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$1.modelCell, children: item.model });
          }
          return /* @__PURE__ */ jsxRuntimeExports.jsx(EmptyCell, {});
        }
      },
      {
        field: "score",
        headerName: "Score",
        initialWidth: 80,
        minWidth: 60,
        maxWidth: 120,
        sortable: true,
        filter: "agNumberColumnFilter",
        resizable: true,
        valueFormatter: (params) => {
          if (params.value === void 0 || params.value === null) return "";
          return formatPrettyDecimal(params.value);
        },
        cellRenderer: (params) => {
          const item = params.data;
          if (!item || item.score === void 0) {
            return /* @__PURE__ */ jsxRuntimeExports.jsx(EmptyCell, {});
          }
          return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$1.scoreCell, children: formatPrettyDecimal(item.score) });
        }
      },
      {
        field: "status",
        headerName: "Status",
        initialWidth: 80,
        minWidth: 60,
        maxWidth: 100,
        sortable: true,
        filter: true,
        resizable: true,
        cellRenderer: (params) => {
          const item = params.data;
          if (!item) return null;
          const status = item.status;
          if (!status && item.type !== "pending-task") {
            return /* @__PURE__ */ jsxRuntimeExports.jsx(EmptyCell, {});
          }
          const icon = item.type === "pending-task" ? ApplicationIcons.pendingTask : status === "error" ? ApplicationIcons.error : status === "started" ? ApplicationIcons.running : status === "cancelled" ? ApplicationIcons.cancelled : ApplicationIcons.success;
          const clz = item.type === "pending-task" ? styles$1.started : status === "error" ? styles$1.error : status === "started" ? styles$1.started : status === "cancelled" ? styles$1.cancelled : styles$1.success;
          return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$1.statusCell, children: /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: clsx(icon, clz) }) });
        }
      },
      {
        field: "completedAt",
        headerName: "Completed",
        initialWidth: 130,
        minWidth: 80,
        maxWidth: 140,
        sortable: true,
        filter: true,
        resizable: true,
        cellDataType: "date",
        filterValueGetter: (params) => {
          if (!params.data?.completedAt) return void 0;
          const d = new Date(params.data.completedAt);
          return new Date(d.getFullYear(), d.getMonth(), d.getDate());
        },
        valueGetter: (params) => {
          const completed = params.data?.completedAt;
          if (!completed) return "";
          return formatDateTime(new Date(completed));
        },
        cellRenderer: (params) => {
          const completed = params.data?.completedAt;
          if (!completed) {
            return /* @__PURE__ */ jsxRuntimeExports.jsx(EmptyCell, {});
          }
          const timeStr = formatDateTime(new Date(completed));
          return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$1.dateCell, children: timeStr });
        },
        comparator: createFolderFirstComparator(comparators.date)
      },
      {
        field: "name",
        headerName: "File Name",
        initialWidth: 600,
        minWidth: 150,
        sortable: true,
        filter: true,
        resizable: true,
        valueGetter: (params) => {
          const item = params.data;
          if (!item || item.type !== "file") return "";
          return basename(item.name);
        },
        cellRenderer: (params) => {
          const item = params.data;
          if (!item || item.type === "folder" || item.type === "pending-task") {
            return /* @__PURE__ */ jsxRuntimeExports.jsx(EmptyCell, {});
          }
          const value = basename(item.name);
          return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$1.nameCell, children: value });
        }
      }
    ];
    const scorerColumns = Object.keys(scorerMap).map(
      (scorerName) => {
        const scoreType = scorerMap[scorerName];
        return {
          field: `score_${scorerName}`,
          headerName: scorerName,
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
            if (typeof value === "number") {
              return formatPrettyDecimal(value);
            }
            return String(value);
          },
          cellRenderer: (params) => {
            const value = params.value;
            if (value === void 0 || value === null || value === "") {
              return /* @__PURE__ */ jsxRuntimeExports.jsx(EmptyCell, {});
            }
            return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$1.scoreCell, children: formatPrettyDecimal(value) });
          },
          comparator: createFolderFirstComparator((valA, valB) => {
            if (typeof valA === "number" && typeof valB === "number") {
              return valA - valB;
            }
            return String(valA || "").localeCompare(String(valB || ""));
          })
        };
      }
    );
    return [...baseColumns, ...scorerColumns];
  }, [scorerMap]);
  const columns = reactExports.useMemo(() => {
    const columnsWithVisibility = allColumns.map((col) => {
      const field = getFieldKey(col);
      const isScoreColumn = field.startsWith("score_");
      const isVisible = columnVisibility[field] ?? (isScoreColumn ? false : true);
      return {
        ...col,
        hide: !isVisible
      };
    });
    return columnsWithVisibility;
  }, [allColumns, columnVisibility]);
  return {
    columns,
    setColumnVisibility
  };
};
const LogListGrid = ({
  items,
  currentPath,
  gridRef: externalGridRef
}) => {
  const {
    gridState,
    setGridState,
    setFilteredCount,
    previousLogPath,
    setPreviousLogPath
  } = useLogsListing();
  const { loadLogOverviews, loadAllLogOverviews } = useLogs();
  const loading = useStore((state) => state.app.status.loading);
  const syncing = useStore((state) => state.app.status.syncing);
  const setWatchedLogs = useStore((state) => state.logsActions.setWatchedLogs);
  const logPreviews = useStore((state) => state.logs.logPreviews);
  const logDetails = useStore((state) => state.logs.logDetails);
  const navigate = useNavigate();
  const internalGridRef = reactExports.useRef(null);
  const gridRef = externalGridRef ?? internalGridRef;
  const gridContainerRef = reactExports.useRef(null);
  const logFiles = reactExports.useMemo(() => {
    return items.filter((item) => item.type === "file").map((item) => item.log).filter((file) => file !== void 0);
  }, [items]);
  const { columns } = useLogListColumns();
  const initialGridState = reactExports.useMemo(() => {
    if (previousLogPath !== void 0 && previousLogPath !== currentPath) {
      const result = { ...gridState };
      delete result.filter;
      return result;
    }
    return gridState;
  }, [currentPath, gridState, previousLogPath]);
  reactExports.useEffect(() => {
    if (currentPath !== previousLogPath) {
      setPreviousLogPath(currentPath);
    }
  }, [currentPath, previousLogPath, setPreviousLogPath]);
  reactExports.useEffect(() => {
    gridContainerRef.current?.focus();
  }, []);
  const data = reactExports.useMemo(() => {
    return items.map((item) => {
      const preview = item.type === "file" ? item.logPreview : void 0;
      const details = item.type === "file" && item.log ? logDetails[item.log.name] : void 0;
      const row = {
        id: item.id,
        name: item.name,
        displayIndex: item.type === "file" || item.type === "pending-task" ? item.displayIndex : void 0,
        type: item.type,
        url: item.url,
        task: item.type === "file" ? preview?.task : item.name,
        model: item.type === "file" ? preview?.model : item.type === "pending-task" ? item.model : void 0,
        score: preview?.primary_metric?.value,
        status: preview?.status,
        completedAt: preview?.completed_at,
        itemCount: item.type === "folder" ? item.itemCount : void 0,
        log: item.type === "file" ? item.log : void 0
      };
      if (details?.results?.scores) {
        for (const evalScore of details.results.scores) {
          if (evalScore.metrics) {
            for (const [metricName, metric] of Object.entries(
              evalScore.metrics
            )) {
              row[`score_${metricName}`] = metric.value;
            }
          }
        }
      }
      return row;
    });
  }, [items, logDetails]);
  const handleRowClick = reactExports.useCallback(
    (e) => {
      if (e.data && e.node && gridRef.current?.api) {
        gridRef.current.api.deselectAll();
        e.node.setSelected(true);
        const mouseEvent = e.event;
        const openInNewWindow = mouseEvent?.metaKey || mouseEvent?.ctrlKey || mouseEvent?.shiftKey || mouseEvent?.button === 1;
        const url = e.data.url;
        if (url) {
          setTimeout(() => {
            if (openInNewWindow) {
              window.open(`#${url}`, "_blank");
            } else {
              navigate(url);
            }
          }, 10);
        }
      }
    },
    [navigate, gridRef]
  );
  const handleOpenRow = reactExports.useCallback(
    (rowNode, e) => {
      if (!rowNode.data?.url) {
        return;
      }
      const openInNewWindow = e.metaKey || e.ctrlKey || e.shiftKey;
      if (openInNewWindow) {
        window.open(`#${rowNode.data.url}`, "_blank");
      } else {
        navigate(rowNode.data.url);
      }
    },
    [navigate]
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
  reactExports.useEffect(() => {
    const loadHeaders = async () => {
      const filesToLoad = logFiles.filter((file) => !logPreviews[file.name]);
      if (filesToLoad.length > 0) {
        await loadLogOverviews(filesToLoad);
      }
      setWatchedLogs(logFiles);
    };
    loadHeaders();
  }, [logFiles, loadLogOverviews, setWatchedLogs, logPreviews]);
  const handleSortChanged = reactExports.useCallback(async () => {
    await loadAllLogOverviews();
    setWatchedLogs(logFiles);
  }, [loadAllLogOverviews, setWatchedLogs, logFiles]);
  const handleFilterChanged = reactExports.useCallback(async () => {
    await loadAllLogOverviews();
    setWatchedLogs(logFiles);
    if (gridRef.current?.api) {
      const displayedRowCount = gridRef.current.api.getDisplayedRowCount();
      setFilteredCount(displayedRowCount);
    }
  }, [
    loadAllLogOverviews,
    setWatchedLogs,
    logFiles,
    setFilteredCount,
    gridRef
  ]);
  const maxColCount = reactExports.useRef(0);
  const resizeGridColumns = reactExports.useRef(createGridColumnResizer(gridRef)).current;
  reactExports.useEffect(() => {
    resizeGridColumns();
  }, [columns, resizeGridColumns]);
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$2.gridWrapper), children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { ref: gridContainerRef, className: styles$2.gridContainer, tabIndex: 0, children: /* @__PURE__ */ jsxRuntimeExports.jsx(
    AgGridReact,
    {
      ref: gridRef,
      rowData: data,
      animateRows: false,
      columnDefs: columns,
      defaultColDef: {
        sortable: true,
        filter: true,
        resizable: true
      },
      autoSizeStrategy: { type: "fitGridWidth" },
      headerHeight: 25,
      rowSelection: { mode: "singleRow", checkboxes: false },
      getRowId: (params) => params.data.id,
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
          const displayedRowCount = gridRef.current.api.getDisplayedRowCount();
          setFilteredCount(displayedRowCount);
        }
      },
      onRowClicked: handleRowClick,
      onSortChanged: handleSortChanged,
      onFilterChanged: handleFilterChanged,
      loading: data.length === 0 && (loading > 0 || syncing)
    }
  ) }) });
};
const panel = "_panel_16dj8_1";
const list = "_list_16dj8_8";
const styles = {
  panel,
  list
};
const rootName = (relativePath) => {
  const parts = relativePath.split("/");
  if (parts.length === 0) {
    return "";
  }
  return parts[0];
};
const LogsPanel = ({ maybeShowSingleLog }) => {
  const { loadLogs } = useLogs();
  const gridRef = reactExports.useRef(null);
  const [showColumnSelector, setShowColumnSelector] = reactExports.useState(false);
  const columnButtonRef = reactExports.useRef(null);
  const showRetriedLogs = useStore((state) => state.logs.showRetriedLogs);
  const setShowRetriedLogs = useStore(
    (state) => state.logsActions.setShowRetriedLogs
  );
  const logDir = useStore((state) => state.logs.logDir);
  const logFiles = useLogsWithretried();
  const evalSet = useStore((state) => state.logs.evalSet);
  const logPreviews = useStore((state) => state.logs.logPreviews);
  const { filteredCount } = useLogsListing();
  const syncing = useStore((state) => state.app.status.syncing);
  const watchedLogs = useStore((state) => state.logs.listing.watchedLogs);
  const navigate = useNavigate();
  const { logPath } = useLogRouteParams();
  const currentDir = join(logPath || "", logDir);
  useFlowServerData(logPath || "");
  const flowData = useStore((state) => state.logs.flow);
  const { startPolling, stopPolling } = useClientEvents();
  const { setDocumentTitle } = useDocumentTitle();
  reactExports.useEffect(() => {
    setDocumentTitle({
      logDir
    });
  }, [setDocumentTitle, logDir]);
  const previousWatchedLogs = reactExports.useRef(void 0);
  reactExports.useEffect(() => {
    const current = watchedLogs?.map((log) => log.name).sort().join(",") || "";
    const previous = previousWatchedLogs.current === void 0 ? void 0 : previousWatchedLogs.current?.map((log) => log.name).sort().join(",") || "";
    if (current !== previous) {
      stopPolling();
      if (watchedLogs !== void 0) {
        startPolling(watchedLogs);
      }
      previousWatchedLogs.current = watchedLogs;
    }
  }, [watchedLogs, startPolling, stopPolling]);
  const [logItems, hasRetriedLogs] = reactExports.useMemo(() => {
    const folderItems = [];
    const fileItems = [];
    const processedFolders = /* @__PURE__ */ new Set();
    const existingLogTaskIds = /* @__PURE__ */ new Set();
    let _hasRetriedLogs = false;
    for (const logFile of logFiles) {
      if (logFile.task_id) {
        existingLogTaskIds.add(logFile.task_id);
      }
      const name = logFile.name;
      const cleanDir = currentDir.endsWith("/") ? currentDir.slice(0, -1) : currentDir;
      const dirWithSlash = !currentDir.endsWith("/") ? currentDir + "/" : currentDir;
      if (isInDirectory(name, cleanDir)) {
        const dirName = directoryRelativeUrl(currentDir, logDir);
        const relativePath = directoryRelativeUrl(name, currentDir);
        const fileOrFolderName = decodeURIComponent(rootName(relativePath));
        const path = join(
          decodeURIComponent(relativePath),
          decodeURIComponent(dirName)
        );
        if (logFile.retried) {
          _hasRetriedLogs = true;
        }
        if (showRetriedLogs || !logFile.retried) {
          fileItems.push({
            id: fileOrFolderName,
            name: fileOrFolderName,
            type: "file",
            url: logsUrl(path, logDir),
            log: logFile,
            logPreview: logPreviews[logFile.name]
          });
        }
      } else if (name.startsWith(dirWithSlash)) {
        const relativePath = directoryRelativeUrl(name, currentDir);
        const dirName = decodeURIComponent(rootName(relativePath));
        const currentDirRelative = directoryRelativeUrl(currentDir, logDir);
        const url = join(dirName, decodeURIComponent(currentDirRelative));
        if (!processedFolders.has(dirName)) {
          folderItems.push({
            id: dirName,
            name: dirName,
            type: "folder",
            url: logsUrl(url, logDir),
            itemCount: logFiles.filter(
              (file) => file.name.startsWith(dirname(name))
            ).length
          });
          processedFolders.add(dirName);
        }
      }
    }
    const orderedItems = [...folderItems, ...fileItems];
    const _logFiles = appendPendingItems(
      evalSet,
      existingLogTaskIds,
      orderedItems
    );
    return [_logFiles, _hasRetriedLogs];
  }, [evalSet, logFiles, currentDir, logDir, logPreviews, showRetriedLogs]);
  const { columns, setColumnVisibility } = useLogListColumns();
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
  const progress = reactExports.useMemo(() => {
    let pending = 0;
    let total = 0;
    for (const item of logItems) {
      if (item.type === "file" || item.type === "pending-task") {
        total += 1;
        if (item.type === "pending-task" || item.logPreview?.status === "started") {
          pending += 1;
        }
      }
    }
    return {
      complete: total - pending,
      total
    };
  }, [logItems]);
  reactExports.useEffect(() => {
    loadLogs(logPath);
  }, [loadLogs, logPath]);
  const handleResetFilters = () => {
    if (gridRef.current?.api) {
      gridRef.current.api.setFilterModel(null);
    }
  };
  const filterModel = gridRef.current?.api?.getFilterModel() || {};
  const filteredFields = Object.keys(filterModel);
  const hasFilter = filteredFields.length > 0;
  reactExports.useEffect(() => {
    if (maybeShowSingleLog && logItems.length === 1) {
      const onlyItem = logItems[0];
      if (onlyItem.url) {
        navigate(onlyItem.url);
      }
    }
  }, [logItems, maybeShowSingleLog, navigate]);
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles.panel), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs(
      ApplicationNavbar,
      {
        fnNavigationUrl: logsUrl,
        currentPath: logPath,
        showActivity: "log",
        children: [
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
              onClick: () => setShowRetriedLogs(!showRetriedLogs)
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
          /* @__PURE__ */ jsxRuntimeExports.jsx(ViewSegmentedControl, { selectedSegment: "logs" }),
          flowData && /* @__PURE__ */ jsxRuntimeExports.jsx(FlowButton, {})
        ]
      }
    ),
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
    /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles.list, "text-size-smaller"), children: /* @__PURE__ */ jsxRuntimeExports.jsx(
        LogListGrid,
        {
          items: logItems,
          currentPath: currentDir,
          gridRef
        }
      ) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        LogListFooter,
        {
          itemCount: logItems.length,
          filteredCount,
          progressText: syncing ? "Syncing data" : void 0,
          progressBar: progress.total !== progress.complete ? /* @__PURE__ */ jsxRuntimeExports.jsx(
            ProgressBar,
            {
              min: 0,
              max: progress.total,
              value: progress.complete,
              width: "100px"
            }
          ) : void 0
        }
      )
    ] })
  ] });
};
const appendPendingItems = (evalSet, tasksWithLogFiles, collapsedLogItems) => {
  const pendingTasks = new Array();
  for (const task of evalSet?.tasks || []) {
    if (!tasksWithLogFiles.has(task.task_id)) {
      pendingTasks.push({
        id: task.task_id,
        name: task.name || "<unknown>",
        model: task.model,
        type: "pending-task"
      });
    }
  }
  pendingTasks.sort((a, b) => a.name.localeCompare(b.name));
  collapsedLogItems.push(...pendingTasks);
  return collapsedLogItems;
};
export {
  LogsPanel
};
//# sourceMappingURL=LogsPanel.js.map
