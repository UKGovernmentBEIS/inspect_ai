import { j as jsxRuntimeExports, K as createPolling, L as createLogger, u as useStore, a as useNavigate, G as useLocation, H as useLogOrSampleRouteParams, A as ApplicationIcons, c as useLogRouteParams, J as useSamplesRouteParams, I as samplesUrl, l as logsUrl, x as debounce } from "./index.js";
import { c as clsx, b as useLogs, T as ToolButton, P as PopOver } from "./ApplicationNavbar.js";
import { b as reactExports } from "./vendor-grid.js";
const container = "_container_1n7pm_1";
const label$2 = "_label_1n7pm_7";
const outer = "_outer_1n7pm_11";
const inner = "_inner_1n7pm_20";
const styles$6 = {
  container,
  label: label$2,
  outer,
  inner
};
const ProgressBar = ({
  min,
  max,
  value,
  label: label2,
  width = "100px"
}) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$6.container), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$6.outer), style: { width }, children: /* @__PURE__ */ jsxRuntimeExports.jsx(
      "div",
      {
        className: clsx(styles$6.inner),
        style: { width: `${(value - min) / (max - min) * 100}%` }
      }
    ) }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$6.label, "text-size-smallest"), children: [
      value,
      " / ",
      max,
      " ",
      label2 || ""
    ] })
  ] });
};
const log$1 = createLogger("Client-Events-Service");
const kRetries = 10;
const kPollingInterval = 5;
const kRefreshEvent = "refresh-evals";
class ClientEventsService {
  currentPolling = null;
  abortController = null;
  isRefreshing = false;
  pendingLogs = /* @__PURE__ */ new Set();
  onRefreshCallback = null;
  setRefreshCallback(callback) {
    this.onRefreshCallback = callback;
  }
  async refreshPendingLogFiles() {
    if (this.isRefreshing || !this.onRefreshCallback) {
      return;
    }
    do {
      try {
        const logFiles = [...this.pendingLogs];
        this.pendingLogs.clear();
        this.isRefreshing = true;
        await this.onRefreshCallback(logFiles);
      } finally {
        this.isRefreshing = false;
      }
    } while (this.pendingLogs.size > 0);
  }
  async refreshLogFiles(logs) {
    logs.forEach((file) => this.pendingLogs.add(file));
    await this.refreshPendingLogFiles();
  }
  startPolling(logs, api) {
    this.stopPolling();
    this.abortController = new AbortController();
    let pollingCount = 1;
    this.currentPolling = createPolling(
      `Client-Events`,
      async () => {
        if (this.abortController?.signal.aborted) {
          log$1.debug(`Component unmounted, stopping poll for client events`);
          return false;
        }
        log$1.debug(`Polling client events`);
        const events = await api?.client_events();
        log$1.debug(`Received events`, events);
        if (this.abortController?.signal.aborted) {
          log$1.debug(`Polling aborted, stopping poll for client events`);
          return false;
        }
        if ((events || []).includes(kRefreshEvent)) {
          await this.refreshLogFiles(logs);
        }
        if (pollingCount++ % 10 === 0) {
          await this.refreshLogFiles(logs);
        }
        return true;
      },
      {
        maxRetries: kRetries,
        interval: kPollingInterval
      }
    );
    this.currentPolling.start();
  }
  stopPolling() {
    if (this.currentPolling) {
      this.currentPolling.stop();
      this.currentPolling = null;
    }
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }
  }
  cleanup() {
    log$1.debug(`Cleanup`);
    this.stopPolling();
    this.pendingLogs.clear();
    this.onRefreshCallback = null;
  }
}
const clientEventsService = new ClientEventsService();
const log = createLogger("Client-Events");
function useClientEvents() {
  const syncLogs = useStore((state) => state.logsActions.syncLogs);
  const logPreviews = useStore((state) => state.logs.logPreviews);
  const api = useStore((state) => state.api);
  const { loadLogOverviews } = useLogs();
  const refreshCallback = reactExports.useCallback(
    async (logs) => {
      log.debug("Refresh Log Files");
      await syncLogs();
      const toRefresh = [];
      for (const log2 of logs) {
        const header = logPreviews[log2.name];
        if (!header || header.status === "started") {
          toRefresh.push(log2);
        }
      }
      if (toRefresh.length > 0) {
        log.debug(`Refreshing ${toRefresh.length} log files`, toRefresh);
        await loadLogOverviews(toRefresh);
      }
    },
    [logPreviews, syncLogs, loadLogOverviews]
  );
  reactExports.useEffect(() => {
    clientEventsService.setRefreshCallback(refreshCallback);
  }, [refreshCallback]);
  const startPolling = reactExports.useCallback(
    (logs) => {
      clientEventsService.startPolling(logs, api);
    },
    [api]
  );
  const stopPolling = reactExports.useCallback(() => {
    clientEventsService.stopPolling();
  }, []);
  const cleanup = reactExports.useCallback(() => {
    clientEventsService.cleanup();
  }, []);
  reactExports.useEffect(() => {
    return () => {
      cleanup();
    };
  }, [cleanup]);
  return {
    startPolling,
    stopPolling,
    cleanup
  };
}
const button$1 = "_button_1bbut_1";
const viewerOptions = "_viewerOptions_1bbut_7";
const styles$5 = {
  button: button$1,
  viewerOptions
};
const FlowButton = reactExports.forwardRef(
  (_, ref) => {
    const navigateRouter = useNavigate();
    const location = useLocation();
    const { logPath } = useLogOrSampleRouteParams();
    const navigate = () => {
      const isSamplesRoute = location.pathname.startsWith("/samples/");
      const routePrefix = isSamplesRoute ? "/samples" : "/logs";
      const flowPath = logPath ? `${routePrefix}/${logPath}/flow.yaml` : `${routePrefix}/flow.yaml`;
      navigateRouter(flowPath);
    };
    return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: /* @__PURE__ */ jsxRuntimeExports.jsx(
      "button",
      {
        ref,
        type: "button",
        className: clsx(styles$5.button),
        onClick: navigate,
        title: "View Flow configuration for this directory",
        children: /* @__PURE__ */ jsxRuntimeExports.jsx(
          "i",
          {
            ref,
            className: clsx(ApplicationIcons.flow, styles$5.viewerOptions)
          }
        )
      }
    ) });
  }
);
const navbarButton = "_navbarButton_1gksz_1";
const styles$4 = {
  navbarButton
};
const NavbarButton = reactExports.forwardRef(
  ({ label: label2, className, icon, latched, ...rest }, ref) => {
    return /* @__PURE__ */ jsxRuntimeExports.jsx(
      ToolButton,
      {
        ref,
        label: label2,
        className: clsx(className, styles$4.navbarButton),
        icon,
        latched,
        ...rest
      }
    );
  }
);
NavbarButton.displayName = "NavbarButton";
const rootControl = "_rootControl_mhb7y_1";
const segment = "_segment_mhb7y_9";
const selected = "_selected_mhb7y_9";
const styles$3 = {
  rootControl,
  segment,
  selected
};
const SegmentedControl = ({
  segments: segments2,
  onSegmentChange,
  selectedId
}) => {
  const handleSegmentClick = reactExports.useCallback(
    (segmentId, index) => {
      onSegmentChange(segmentId, index);
    },
    [onSegmentChange]
  );
  if (selectedId === void 0) {
    selectedId = segments2[0]?.id;
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$3.rootControl), children: segments2.map((segment2, index) => /* @__PURE__ */ jsxRuntimeExports.jsxs(
    "button",
    {
      className: clsx(
        styles$3.segment,
        {
          [styles$3.selected]: selectedId === segment2.id
        },
        "text-size-smallest",
        "text-style-secondary"
      ),
      onClick: () => handleSegmentClick(segment2.id, index),
      "aria-pressed": selectedId === segment2.id,
      children: [
        segment2.icon && /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: segment2.icon }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: segment2.label })
      ]
    },
    segment2.id
  )) });
};
const segments = [
  { id: "logs", label: "Tasks", icon: ApplicationIcons.navbar.tasks },
  { id: "samples", label: "Samples", icon: ApplicationIcons.sample }
];
const ViewSegmentedControl = ({
  selectedSegment
}) => {
  const navigate = useNavigate();
  const { logPath } = useLogRouteParams();
  const { samplesPath } = useSamplesRouteParams();
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    SegmentedControl,
    {
      segments,
      selectedId: selectedSegment,
      onSegmentChange: (segment2) => {
        if (segment2 === "samples") {
          const path = logPath || samplesPath || "";
          const sampleUrl = samplesUrl(path);
          navigate(sampleUrl);
        } else {
          const path = samplesPath || logPath || "";
          const logUrl = logsUrl(path);
          navigate(logUrl);
        }
      }
    }
  );
};
const checkboxWrapper = "_checkboxWrapper_vtlwq_1";
const label$1 = "_label_vtlwq_5";
const checkbox = "_checkbox_vtlwq_1";
const filterIcon = "_filterIcon_vtlwq_16";
const scrollableContainer = "_scrollableContainer_vtlwq_21";
const section = "_section_vtlwq_26";
const headerRow = "_headerRow_vtlwq_30";
const buttonContainer = "_buttonContainer_vtlwq_39";
const button = "_button_vtlwq_39";
const columnsLayout = "_columnsLayout_vtlwq_54";
const styles$2 = {
  checkboxWrapper,
  label: label$1,
  checkbox,
  filterIcon,
  scrollableContainer,
  section,
  headerRow,
  buttonContainer,
  button,
  columnsLayout
};
const getFieldKey = (col) => {
  return col.field || col.headerName || "?";
};
const createGridColumnResizer = (gridRef, delayMs = 10) => {
  return debounce(() => {
    gridRef.current?.api?.sizeColumnsToFit();
  }, delayMs);
};
const ColumnSelectorPopover = ({
  showing,
  setShowing,
  columns,
  onVisibilityChange,
  positionEl,
  filteredFields = []
}) => {
  const currentVisibility = reactExports.useMemo(
    () => columns.reduce(
      (acc, col) => ({ ...acc, [getFieldKey(col)]: !col.hide }),
      {}
    ),
    [columns]
  );
  const handleToggle = (field) => {
    onVisibilityChange({
      ...currentVisibility,
      [field]: !currentVisibility[field]
    });
  };
  const columnGroups = reactExports.useMemo(() => {
    return {
      base: columns.filter((col) => !getFieldKey(col).startsWith("score_")),
      scores: columns.filter((col) => getFieldKey(col).startsWith("score_"))
    };
  }, [columns]);
  const handleSelectAllBase = () => {
    onVisibilityChange({
      ...currentVisibility,
      ...Object.fromEntries(
        columnGroups.base.map((col) => [getFieldKey(col), true])
      )
    });
  };
  const handleDeselectAllBase = () => {
    onVisibilityChange({
      ...currentVisibility,
      ...Object.fromEntries(
        columnGroups.base.map((col) => [getFieldKey(col), false])
      )
    });
  };
  const handleSelectAllScores = () => {
    onVisibilityChange({
      ...currentVisibility,
      ...Object.fromEntries(
        columnGroups.scores.map((col) => [getFieldKey(col), true])
      )
    });
  };
  const handleDeselectAllScores = () => {
    onVisibilityChange({
      ...currentVisibility,
      ...Object.fromEntries(
        columnGroups.scores.map((col) => [getFieldKey(col), false])
      )
    });
  };
  const renderColumnCheckbox = (col) => {
    const field = getFieldKey(col);
    const hasFilter = filteredFields.includes(field);
    return /* @__PURE__ */ jsxRuntimeExports.jsx(
      "div",
      {
        className: styles$2.checkboxWrapper,
        title: hasFilter ? "Unselecting will remove an active filter on this column" : void 0,
        children: /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { className: styles$2.label, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "input",
            {
              type: "checkbox",
              checked: currentVisibility[field],
              onChange: () => handleToggle(field),
              className: styles$2.checkbox
            }
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: col.headerName || field }),
          hasFilter && /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: `${ApplicationIcons.filter} ${styles$2.filterIcon}` })
        ] })
      },
      field
    );
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    PopOver,
    {
      id: "column-selector-popover",
      isOpen: showing,
      setIsOpen: setShowing,
      positionEl,
      placement: "bottom-start",
      showArrow: false,
      hoverDelay: -1,
      className: styles$2.popover,
      children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$2.scrollableContainer, "text-size-small"), children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$2.section), children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: styles$2.headerRow, children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("b", { children: "Base" }),
            /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$2.buttonContainer, "text-size-small"), children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx(
                "a",
                {
                  className: clsx(styles$2.button, "text-size-small"),
                  onClick: handleSelectAllBase,
                  children: "All"
                }
              ),
              "|",
              /* @__PURE__ */ jsxRuntimeExports.jsx(
                "a",
                {
                  className: clsx(styles$2.button),
                  onClick: handleDeselectAllBase,
                  children: "None"
                }
              )
            ] })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$2.columnsLayout, children: columnGroups.base.map((col) => renderColumnCheckbox(col)) })
        ] }),
        columnGroups.scores.length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: styles$2.headerRow, children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("b", { children: "Scorers" }),
            /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: styles$2.buttonContainer, children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx(
                "a",
                {
                  className: clsx(styles$2.button),
                  onClick: handleSelectAllScores,
                  children: "All"
                }
              ),
              "|",
              /* @__PURE__ */ jsxRuntimeExports.jsx(
                "a",
                {
                  className: clsx(styles$2.button),
                  onClick: handleDeselectAllScores,
                  children: "None"
                }
              )
            ] })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$2.columnsLayout, children: columnGroups.scores.map((col) => renderColumnCheckbox(col)) })
        ] })
      ] })
    }
  );
};
function createFolderFirstComparator(compareFn) {
  return (valueA, valueB, nodeA, nodeB) => {
    const itemA = nodeA.data;
    const itemB = nodeB.data;
    if (!itemA || !itemB) return 0;
    if (itemA.type !== itemB.type) {
      return itemA.type === "folder" ? -1 : 1;
    }
    return compareFn(valueA, valueB, itemA, itemB);
  };
}
const comparators = {
  /** Compare values as numbers */
  number: (a, b) => {
    return Number(a || 0) - Number(b || 0);
  },
  /** Compare values as dates */
  date: (a, b) => {
    const timeA = a ? new Date(a).getTime() : 0;
    const timeB = b ? new Date(b).getTime() : 0;
    return timeA - timeB;
  }
};
const gridWrapper = "_gridWrapper_anqm2_5";
const gridContainer = "_gridContainer_anqm2_11";
const iconCell = "_iconCell_anqm2_19";
const numberCell = "_numberCell_anqm2_33";
const taskText = "_taskText_anqm2_43";
const folder = "_folder_anqm2_50";
const fullWidthHeight = "_fullWidthHeight_anqm2_56";
const styles$1 = {
  gridWrapper,
  gridContainer,
  iconCell,
  numberCell,
  taskText,
  folder,
  fullWidthHeight
};
const footer = "_footer_14uod_1";
const spinnerContainer = "_spinnerContainer_14uod_11";
const spinner = "_spinner_14uod_11";
const label = "_label_14uod_25";
const right = "_right_14uod_30";
const left = "_left_14uod_39";
const center = "_center_14uod_48";
const styles = {
  footer,
  spinnerContainer,
  spinner,
  label,
  right,
  left,
  center
};
const LogListFooter = ({
  itemCount,
  itemCountLabel,
  filteredCount,
  progressText,
  progressBar
}) => {
  const effectiveItemCount = filteredCount ?? itemCount;
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx("text-size-smaller", styles.footer), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles.left), children: progressText ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles.spinnerContainer), children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "div",
        {
          className: clsx("spinner-border", styles.spinner),
          role: "status",
          children: /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: clsx("visually-hidden"), children: [
            progressText,
            "..."
          ] })
        }
      ),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx("text-style-secondary", styles.label), children: [
        progressText,
        "..."
      ] })
    ] }) : null }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles.center) }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles.right), children: progressBar ? progressBar : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: effectiveItemCount === 0 ? "" : filteredCount !== void 0 && filteredCount !== itemCount ? `${effectiveItemCount} / ${itemCount} ${itemCountLabel || "items"}` : `${effectiveItemCount} ${itemCountLabel || "items"}` }) })
  ] });
};
export {
  ColumnSelectorPopover as C,
  FlowButton as F,
  LogListFooter as L,
  NavbarButton as N,
  ProgressBar as P,
  ViewSegmentedControl as V,
  comparators as a,
  createGridColumnResizer as b,
  createFolderFirstComparator as c,
  getFieldKey as g,
  styles$1 as s,
  useClientEvents as u
};
//# sourceMappingURL=LogListFooter.js.map
