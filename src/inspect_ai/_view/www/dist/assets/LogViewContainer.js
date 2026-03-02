import { u as useStore, a as useNavigate, h as useParams, k as logsUrlRaw, l as logsUrl, j as jsxRuntimeExports, A as ApplicationIcons, m as kLogViewErrorTabId, n as kLogViewInfoTabId, o as api, p as kLogViewJsonTabId, f as filename, q as kLogViewModelsTabId, r as kScoreTypeBoolean, s as kScoreTypeOther, t as kScoreTypeNumeric, v as kScoreTypeCategorical, w as kScoreTypePassFail, x as debounce, y as kLogViewSamplesTabId, z as kLogViewTaskTabId, B as kModelNone, c as useLogRouteParams, E as ErrorPanel, C as useSearchParams, D as logSamplesUrl, F as baseUrl } from "./index.js";
import { b as reactExports, A as AgGridReact, t as themeBalham } from "./vendor-grid.js";
import { E as ExpandablePanel, R as RenderedContent, c as clsx, g as ANSIDisplay, h as useMessageVisibility, M as MetaDataGrid, i as RecordTree, j as useTotalSampleCount, T as ToolButton, J as JSONPanel, K as KEYWORDS, k as MATH_FUNCTIONS, S as SAMPLE_FUNCTIONS, l as SAMPLE_VARIABLES, m as kSampleMetadataVariable, n as kSampleIdVariable, o as useEvalDescriptor, s as sampleFilterItems, P as PopOver, p as useScores, q as useSelectedScores, r as errorType, t as inputString, v as arrayToString, w as RenderedText, x as useSampleDescriptor, y as formatNoDecimal, e as useDocumentTitle, z as useFilteredSamples, B as toTitleCase, C as formatDuration, a as formatDateTime, D as formatNumber, f as formatPrettyDecimal, F as useProperty, G as CopyButton, H as useSampleInvalidation, L as LabeledValue, I as formatDataset, N as useRefreshLog, O as useEvalSpec, A as ApplicationNavbar, Q as ActivityBar, U as useSampleSummaries, V as usePrevious } from "./ApplicationNavbar.js";
import { C as Card, a as CardHeader, b as CardBody, M as ModelTokenTable, P as PulsingDots, t as truncateMarkdown, N as NoContentsPanel, I as InlineSampleDisplay, E as EmptyPanel, T as TabSet, c as TabPanel, d as ExtendedFindProvider, F as FindBand } from "./InlineSampleDisplay.js";
import { S as StreamLanguage, t as tags, a as StringStream, s as startCompletion, C as Compartment, b as autocompletion, l as linter, E as EditorView, c as EditorState, m as minimalSetup, d as bracketMatching, e as syntaxHighlighting, H as HighlightStyle } from "./vendor-codemirror.js";
import { u as useSampleNavigation } from "./sampleNavigation.js";
import { c as createGridKeyboardHandler } from "./gridKeyboardNavigation.js";
import "./vendor-prism.js";
import "./vendor-asciinema.js";
const useUnloadLog = () => {
  const clearSelectedLogDetails = useStore(
    (state) => state.logActions.clearSelectedLogDetails
  );
  const clearSelectedLogFile = useStore(
    (state) => state.logsActions.clearSelectedLogFile
  );
  const clearLog = useStore((state) => state.logActions.clearLog);
  const unloadLog = reactExports.useCallback(() => {
    clearSelectedLogDetails();
    clearSelectedLogFile();
    clearLog();
  }, [clearLog, clearSelectedLogDetails, clearSelectedLogFile]);
  return { unloadLog };
};
const useLogNavigation = () => {
  const navigate = useNavigate();
  const { logPath } = useParams();
  const logDir = useStore((state) => state.logs.logDir);
  const loadedLog = useStore((state) => state.log.loadedLog);
  const selectTab = reactExports.useCallback(
    (tabId) => {
      if (loadedLog && logPath) {
        const url = logsUrlRaw(logPath, tabId);
        navigate(url);
      } else if (loadedLog) {
        const url = logsUrl(loadedLog, logDir, tabId);
        navigate(url);
      }
    },
    [loadedLog, logPath, logDir, navigate]
  );
  return {
    selectTab
  };
};
const workspace = "_workspace_1r3mu_1";
const tabContainer = "_tabContainer_1r3mu_6";
const tabSet = "_tabSet_1r3mu_14";
const tabs = "_tabs_1r3mu_21";
const tabPanels = "_tabPanels_1r3mu_29";
const styles$s = {
  workspace,
  tabContainer,
  tabSet,
  tabs,
  tabPanels
};
const message = "_message_1gb2h_5";
const styles$r = {
  "task-error-display": "_task-error-display_1gb2h_1",
  message
};
const TaskErrorCard = ({ error: error2 }) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(Card, { children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      CardHeader,
      {
        icon: ApplicationIcons.error,
        label: `Task Failed`
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsxs(CardBody, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        ExpandablePanel,
        {
          id: "task-error-collapse",
          collapse: true,
          className: clsx("text-size-smaller", styles$r.message),
          children: /* @__PURE__ */ jsxRuntimeExports.jsx(
            RenderedContent,
            {
              id: "task-error-message",
              entry: { name: "error", value: error2.message }
            }
          )
        }
      ),
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        ANSIDisplay,
        {
          output: error2.traceback_ansi,
          className: styles$r["task-error-display"]
        }
      )
    ] })
  ] });
};
const useErrorTabConfig = (evalError) => {
  const scrollRef = reactExports.useRef(null);
  return reactExports.useMemo(() => {
    return {
      id: kLogViewErrorTabId,
      label: "Error",
      scrollable: true,
      component: ErrorTab,
      componentProps: {
        evalError,
        scrollRef
      },
      scrollRef
    };
  }, [evalError]);
};
const ErrorTab = ({ evalError }) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { width: "100%" }, children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { padding: "0.5em 1em 0 1em", width: "100%" }, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      TaskErrorCard,
      {
        error: evalError || {
          message: "Unknown error",
          traceback: "",
          traceback_ansi: ""
        }
      }
    ),
    " "
  ] }) });
};
const MessageBand = ({
  id,
  message: message2,
  type,
  scope = "eval"
}) => {
  const className = [type];
  const [visible, setVisible] = useMessageVisibility(id, scope);
  const handleClick = reactExports.useCallback(() => {
    setVisible(false);
  }, [setVisible]);
  if (!visible) {
    className.push("hidden");
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx("message-band", className), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: ApplicationIcons.logging[type] }),
    message2,
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "button",
      {
        className: clsx("btn", "message-band-btn", type),
        title: "Close",
        onClick: handleClick,
        children: /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: ApplicationIcons.close })
      }
    )
  ] });
};
const item$1 = "_item_1uzhd_1";
const styles$q = {
  item: item$1
};
const DatasetDetailView = ({
  dataset,
  style
}) => {
  const filtered = Object.fromEntries(
    Object.entries(dataset).filter(([key]) => key !== "sample_ids")
  );
  if (!dataset || Object.keys(filtered).length === 0) {
    return /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: clsx("text-size-base", styles$q.item), style, children: "No dataset information available" });
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    MetaDataGrid,
    {
      className: clsx("text-size-base", styles$q.item),
      entries: filtered,
      style,
      plain: true
    }
  );
};
const icon$1 = "_icon_59zaz_1";
const container$8 = "_container_59zaz_5";
const metadata = "_metadata_59zaz_11";
const styles$p = {
  icon: icon$1,
  container: container$8,
  metadata
};
const DetailStep = ({
  icon: icon2,
  name,
  params,
  className
}) => {
  const iconHtml = icon2 ? /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: clsx(icon2, styles$p.icon) }) : "";
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(className), children: [
    iconHtml,
    " ",
    name,
    params && Object.keys(params).length > 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$p.container, children: /* @__PURE__ */ jsxRuntimeExports.jsx(
      MetaDataGrid,
      {
        entries: params,
        className: clsx("text-size-small", styles$p.metadata)
      }
    ) }) : ""
  ] });
};
const item = "_item_leq25_1";
const styles$o = {
  item
};
const ScorerDetailView = ({
  name,
  scores,
  params
}) => {
  if (scores.length > 1) {
    params = { ...params, ["scores"]: scores };
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    DetailStep,
    {
      icon: ApplicationIcons.scorer,
      name,
      params,
      className: clsx(styles$o.item, "text-size-base")
    }
  );
};
const container$7 = "_container_12j2k_1";
const separator = "_separator_12j2k_11";
const styles$n = {
  container: container$7,
  separator
};
const SolversDetailView = ({ steps }) => {
  const separator2 = /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$n.items, "text-size-small", styles$n.separator), children: /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: ApplicationIcons.arrows.right }) });
  const details = steps?.map((step, index) => {
    return /* @__PURE__ */ jsxRuntimeExports.jsxs(reactExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        DetailStep,
        {
          name: step.solver,
          className: clsx(styles$n.items, "text-size-small")
        }
      ),
      index < steps.length - 1 ? separator2 : ""
    ] }, `solver-step-${index}`);
  });
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$n.container, children: details });
};
const floatingCol = "_floatingCol_1n79r_1";
const wideCol = "_wideCol_1n79r_9";
const planCol = "_planCol_1n79r_24";
const container$6 = "_container_1n79r_29";
const grid$3 = "_grid_1n79r_35";
const styles$m = {
  floatingCol,
  wideCol,
  planCol,
  container: container$6,
  grid: grid$3
};
const PlanDetailView = ({
  evaluation,
  plan,
  scores
}) => {
  if (!evaluation) {
    return null;
  }
  const steps = plan?.steps;
  const taskColumns = [];
  taskColumns.push({
    title: "Dataset",
    className: styles$m.floatingCol,
    contents: /* @__PURE__ */ jsxRuntimeExports.jsx(DatasetDetailView, { dataset: evaluation.dataset })
  });
  if (steps) {
    taskColumns.push({
      title: "Solvers",
      className: styles$m.wideCol,
      contents: /* @__PURE__ */ jsxRuntimeExports.jsx(SolversDetailView, { steps })
    });
  }
  if (scores) {
    const scorers = scores.reduce(
      (accum, score2) => {
        if (!accum[score2.scorer]) {
          accum[score2.scorer] = {
            scores: [score2.name],
            params: score2.params
          };
        } else {
          accum[score2.scorer].scores.push(score2.name);
        }
        return accum;
      },
      {}
    );
    if (Object.keys(scorers).length > 0) {
      const label2 = Object.keys(scorers).length === 1 ? "Scorer" : "Scorers";
      const scorerPanels = Object.keys(scorers).map((key) => {
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          ScorerDetailView,
          {
            name: key,
            scores: scorers[key].scores,
            params: scorers[key].params
          },
          key
        );
      });
      taskColumns.push({
        title: label2,
        className: styles$m.floatingCol,
        contents: scorerPanels
      });
    }
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$m.container, children: /* @__PURE__ */ jsxRuntimeExports.jsx(
    "div",
    {
      className: styles$m.grid,
      style: {
        gridTemplateColumns: `repeat(${taskColumns.length}, fit-content(50%))`
      },
      children: taskColumns.map((col) => {
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          PlanColumn,
          {
            title: col.title,
            className: col.className,
            children: col.contents
          },
          `plan-col-${col.title}`
        );
      })
    }
  ) });
};
const PlanColumn = ({ title, className, children }) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(className), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "div",
      {
        className: clsx(
          "card-subheading",
          "text-size-small",
          "text-style-label",
          "text-style-secondary",
          styles$m.planCol
        ),
        children: title
      }
    ),
    children
  ] });
};
const PlanCard = ({
  evalSpec,
  evalPlan,
  scores,
  scrollRef
}) => {
  const metadata2 = evalSpec?.metadata || {};
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs(Card, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(CardHeader, { label: "Summary" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(CardBody, { id: "task-plan-card-body", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
        PlanDetailView,
        {
          evaluation: evalSpec,
          plan: evalPlan,
          scores
        }
      ) })
    ] }),
    Object.keys(metadata2).length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs(Card, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(CardHeader, { label: "Metadata" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(CardBody, { id: "task-metadata`", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
        RecordTree,
        {
          id: "plan-md-metadata",
          record: metadata2,
          scrollRef
        }
      ) })
    ] })
  ] });
};
const useInfoTabConfig = (evalSpec, evalPlan, evalError, evalResults, evalStatus) => {
  const scrollRef = reactExports.useRef(null);
  const totalSampleCount = useTotalSampleCount();
  return reactExports.useMemo(() => {
    return {
      id: kLogViewInfoTabId,
      label: "Info",
      scrollable: true,
      component: InfoTab,
      componentProps: {
        evalSpec,
        evalPlan,
        evalError,
        evalResults,
        evalStatus,
        sampleCount: totalSampleCount,
        scrollRef
      },
      scrollRef
    };
  }, [
    evalSpec,
    evalPlan,
    evalError,
    evalResults,
    evalStatus,
    totalSampleCount
  ]);
};
const InfoTab = ({
  evalSpec,
  evalPlan,
  evalResults,
  evalStatus,
  sampleCount,
  scrollRef
}) => {
  const showWarning = sampleCount === 0 && evalStatus === "success" && evalSpec?.dataset.samples && evalSpec.dataset.samples > 0;
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { width: "100%" }, children: [
    showWarning ? /* @__PURE__ */ jsxRuntimeExports.jsx(
      MessageBand,
      {
        id: "sample-too-large",
        message: "Unable to display samples (this evaluation log may be too large).",
        type: "warning"
      }
    ) : "",
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { padding: "0.5em 1em 0 1em", width: "100%" }, children: /* @__PURE__ */ jsxRuntimeExports.jsx(
      PlanCard,
      {
        evalSpec,
        evalPlan,
        scores: evalResults?.scores,
        scrollRef
      }
    ) })
  ] });
};
const DownloadButton = ({
  label: label2,
  fileName,
  fileContents
}) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    "button",
    {
      className: "btn btn-outline-primary download-button",
      onClick: async () => {
        await api.download_file(fileName, fileContents);
      },
      children: label2
    }
  );
};
const DownloadPanel = ({
  message: message2,
  buttonLabel,
  fileName,
  fileContents
}) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "download-panel", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "download-panel-message", children: message2 }),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      DownloadButton,
      {
        label: buttonLabel,
        fileName,
        fileContents
      }
    )
  ] }) });
};
const jsonTab = "_jsonTab_6pq03_1";
const styles$l = {
  jsonTab
};
const kJsonMaxSize = 1e7;
const useJsonTabConfig = (evalVersion, evalStatus, evalSpec, evalPlan, evalError, evalResults, evalStats) => {
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  const selectedTab = useStore((state) => state.app.tabs.workspace);
  return reactExports.useMemo(() => {
    const evalHeader = {
      version: evalVersion,
      status: evalStatus,
      eval: evalSpec,
      plan: evalPlan,
      error: evalError,
      results: evalResults,
      stats: evalStats
    };
    return {
      id: kLogViewJsonTabId,
      label: "JSON",
      scrollable: true,
      component: JsonTab,
      componentProps: {
        logFile: selectedLogFile,
        json: JSON.stringify(evalHeader, null, 2),
        selected: selectedTab === kLogViewJsonTabId
      },
      tools: () => [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          ToolButton,
          {
            label: "Copy JSON",
            icon: ApplicationIcons.copy,
            className: clsx("task-btn-json-copy", "clipboard-button"),
            "data-clipboard-target": "#task-json-contents",
            onClick: copyFeedback
          },
          "copy-json"
        )
      ]
    };
  }, [
    selectedLogFile,
    evalVersion,
    evalStatus,
    evalSpec,
    evalPlan,
    evalError,
    evalResults,
    evalStats,
    selectedTab
  ]);
};
const copyFeedback = (e) => {
  const textEl = e.currentTarget.querySelector(".task-btn-copy-content");
  const iconEl = e.currentTarget.querySelector("i.bi");
  if (textEl) {
    const htmlEl = textEl;
    const htmlIconEl = iconEl;
    const oldText = htmlEl.innerText;
    const oldIconClz = htmlIconEl.className;
    htmlEl.innerText = "Copied!";
    htmlIconEl.className = `${ApplicationIcons.confirm}`;
    setTimeout(() => {
      window.getSelection()?.removeAllRanges();
    }, 50);
    setTimeout(() => {
      htmlEl.innerText = oldText;
      htmlIconEl.className = oldIconClz;
    }, 1250);
  }
};
const JsonTab = ({ logFile, json }) => {
  const downloadFiles = useStore((state) => state.capabilities.downloadFiles);
  if (logFile && json.length > kJsonMaxSize && downloadFiles) {
    const file = `${filename(logFile)}.json`;
    return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$l.jsonTab, children: /* @__PURE__ */ jsxRuntimeExports.jsx(
      DownloadPanel,
      {
        message: "The JSON for this log file is too large to render.",
        buttonLabel: "Download JSON File",
        fileName: file,
        fileContents: json
      }
    ) });
  } else {
    return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$l.jsonTab, children: /* @__PURE__ */ jsxRuntimeExports.jsx(JSONPanel, { id: "task-json-contents", json, simple: true }) });
  }
};
const container$5 = "_container_4wzpj_1";
const modelInfo = "_modelInfo_4wzpj_8";
const role = "_role_4wzpj_15";
const sep = "_sep_4wzpj_19";
const styles$k = {
  container: container$5,
  modelInfo,
  role,
  sep
};
const ModelCard = ({ evalSpec }) => {
  if (!evalSpec) {
    return void 0;
  }
  const modelsInfo = {
    eval: {
      model: evalSpec.model,
      base_url: evalSpec.model_base_url,
      config: evalSpec.model_generate_config,
      args: evalSpec.model_args
    },
    ...evalSpec.model_roles
  };
  const noneEl = /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "text-style-secondary", children: "None" });
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(Card, { children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(CardHeader, { label: "Models" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx(CardBody, { id: "task-model-card-body", children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$k.container, children: Object.keys(modelsInfo || {}).map((modelKey) => {
      const modelInfo2 = modelsInfo[modelKey];
      return /* @__PURE__ */ jsxRuntimeExports.jsxs(
        "div",
        {
          className: clsx(styles$k.modelInfo, "text-size-small"),
          children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              "div",
              {
                className: clsx(
                  styles$k.role,
                  "text-style-label",
                  "text-style-secondary"
                ),
                children: modelKey
              }
            ),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$k.sep) }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-style-label"), children: "Model" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: modelInfo2.model }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$k.sep) }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-style-label"), children: "Base Url" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "text-size-small", children: modelInfo2.base_url || noneEl }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$k.sep) }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-style-label"), children: "Configuration" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "text-size-small", children: modelInfo2.config && Object.keys(modelInfo2.config).length > 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx(
              MetaDataGrid,
              {
                entries: modelInfo2.config
              }
            ) : noneEl }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$k.sep) }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-style-label"), children: "Args" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "text-size-small", children: Object.keys(modelInfo2.args).length > 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx(
              MetaDataGrid,
              {
                entries: modelInfo2.args
              }
            ) : noneEl }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$k.sep) })
          ]
        },
        modelKey
      );
    }) }) })
  ] });
};
const cardsContainer = "_cardsContainer_d0qjo_1";
const styles$j = {
  cardsContainer
};
const kModelUsageCardBodyId = "model-usage-card-body";
const kRoleUsageCardBodyId = "role-usage-card-body";
const UsageCard = ({ stats }) => {
  if (!stats) {
    return null;
  }
  const hasRoleUsage = stats.role_usage && Object.keys(stats.role_usage).length > 0;
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: styles$j.cardsContainer, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs(Card, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(CardHeader, { label: "Model Usage" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(CardBody, { id: kModelUsageCardBodyId, children: /* @__PURE__ */ jsxRuntimeExports.jsx(ModelTokenTable, { model_usage: stats.model_usage }) })
    ] }),
    hasRoleUsage && /* @__PURE__ */ jsxRuntimeExports.jsxs(Card, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(CardHeader, { label: "Role Usage" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(CardBody, { id: kRoleUsageCardBodyId, children: /* @__PURE__ */ jsxRuntimeExports.jsx(ModelTokenTable, { model_usage: stats.role_usage }) })
    ] })
  ] });
};
const useModelsTab = (evalSpec, evalStats, evalStatus) => {
  return reactExports.useMemo(() => {
    return {
      id: kLogViewModelsTabId,
      label: "Models",
      scrollable: true,
      component: ModelTab,
      componentProps: {
        evalSpec,
        evalStats,
        evalStatus
      }
    };
  }, [evalSpec, evalStats, evalStatus]);
};
const ModelTab = ({
  evalSpec,
  evalStats,
  evalStatus
}) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { width: "100%" }, children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { padding: "0.5em 1em 0 1em", width: "100%" }, children: [
    evalSpec ? /* @__PURE__ */ jsxRuntimeExports.jsx(ModelCard, { evalSpec }) : void 0,
    evalStatus !== "started" && evalStats?.model_usage && Object.keys(evalStats.model_usage).length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx(UsageCard, { stats: evalStats })
  ] }) });
};
const TOKEN_PATTERNS = {
  STRING: /^"[^"]*"/,
  UNTERMINATED_STRING: /^"[^"]*/,
  NUMBER: /^(-|\+)?\d+(\.\d+)?/,
  RELATION: /^(==|!=|<=|>=|<|>|~=)/,
  MISC_OPERATOR: /^(=|!|~)/,
  OPERATOR: /^(\+|-|\*|\/|\^|\(|\)|,|\.)/,
  VARIABLE: /^[a-zA-Z_][a-zA-Z0-9_]*/
};
const createWordRegex = (words) => new RegExp(`^(${words.join("|")})\\b`);
const countSpaces = (word) => word.split(" ").length - 1;
const mathFunctionsRegex = createWordRegex(
  MATH_FUNCTIONS.map(([label2]) => label2)
);
const sampleFunctionsRegex = createWordRegex(
  SAMPLE_FUNCTIONS.map(([label2]) => label2)
);
const keywordsRegex = createWordRegex(
  // Ensure 'not in' matches first
  KEYWORDS.sort((a, b) => countSpaces(b) - countSpaces(a))
);
function nextToken(stream) {
  if (stream.match(TOKEN_PATTERNS.STRING)) return "string";
  if (stream.match(TOKEN_PATTERNS.UNTERMINATED_STRING))
    return "unterminatedString";
  if (stream.match(TOKEN_PATTERNS.NUMBER)) return "number";
  if (stream.match(keywordsRegex)) return "keyword";
  if (stream.match(mathFunctionsRegex)) return "mathFunction";
  if (stream.match(sampleFunctionsRegex)) return "sampleFunction";
  if (stream.match(TOKEN_PATTERNS.VARIABLE)) return "variable";
  if (stream.match(TOKEN_PATTERNS.RELATION)) return "relation";
  if (stream.match(TOKEN_PATTERNS.MISC_OPERATOR)) return "miscOperator";
  if (stream.match(TOKEN_PATTERNS.OPERATOR)) return "miscOperator";
  stream.next();
  return null;
}
function tokenize(input2) {
  const tokens = [];
  const stream = new StringStream(input2, 0, 0);
  while (stream.pos < input2.length) {
    const from = stream.pos;
    const type = nextToken(stream);
    if (type) {
      tokens.push({
        type,
        text: input2.slice(from, stream.pos),
        from,
        to: stream.pos
      });
    }
  }
  return tokens;
}
const language = StreamLanguage.define({
  token: nextToken,
  tokenTable: {
    string: tags.string,
    unterminatedString: tags.string,
    number: tags.number,
    keyword: tags.keyword,
    mathFunction: tags.function(tags.variableName),
    sampleFunction: tags.function(tags.variableName),
    variable: tags.variableName,
    relation: tags.operator,
    miscOperator: tags.operator
  }
});
const isLiteral = (token) => ["string", "unterminatedString", "number"].includes(token?.type);
const isLogicalOp = (token) => ["and", "or", "not"].includes(token?.text);
const autocompleteImmediatelyAfter = (token) => ["(", "."].includes(token?.text);
const applyWithCall = (view, completion, from, to) => {
  view.dispatch({
    changes: { from, to, insert: `${completion.label}()` },
    selection: { anchor: from + completion.label.length + 1 }
  });
};
const applyWithDot = (view, completion, from, to) => {
  view.dispatch({
    changes: { from, to, insert: `${completion.label}.` },
    selection: { anchor: from + completion.label.length + 1 }
  });
  setTimeout(() => startCompletion(view), 0);
};
const applyWithSpace = (view, completion, from, to) => {
  view.dispatch({
    changes: { from, to, insert: `${completion.label} ` },
    selection: { anchor: from + completion.label.length + 1 }
  });
  setTimeout(() => startCompletion(view), 0);
};
const makeKeywordCompletion = (k) => ({
  label: k,
  type: "keyword",
  boost: -20
});
const makeMathFunctionCompletion = ([label2, info]) => ({
  label: label2,
  type: "function",
  info,
  apply: applyWithCall,
  boost: -10
});
const makeSampleFunctionCompletion = ([label2, info]) => ({
  label: label2,
  type: "function",
  info,
  apply: applyWithCall,
  boost: 0
});
const makeSampleVariableCompletion = ([label2, info]) => ({
  label: label2,
  type: "variable",
  info,
  apply: label2 === kSampleMetadataVariable ? applyWithDot : label2 === kSampleIdVariable ? applyWithSpace : void 0,
  boost: 10
});
const makeLiteralCompletion = (k) => ({
  label: k,
  type: "text",
  boost: 20
});
const makeCanonicalNameCompletion = (item2, { autoSpaceIf = () => false } = {}) => ({
  label: item2.canonicalName + (autoSpaceIf(item2) ? " " : ""),
  type: "variable",
  info: item2.tooltip,
  boost: 30
});
const makeMemberAccessCompletion = (item2) => ({
  label: item2.qualifiedName?.split(".")[1] || "",
  type: "variable",
  info: item2.tooltip,
  boost: 40
});
const getMemberScoreItems = (filterItems, scorer2) => filterItems.filter((item2) => item2?.qualifiedName?.startsWith(`${scorer2}.`));
const getSampleIds = (samples) => {
  const ids = /* @__PURE__ */ new Set();
  for (const sample of samples) {
    ids.add(sample.id);
  }
  return ids;
};
const getMetadataPropertyValues = (samples, propertyPath) => {
  const values = /* @__PURE__ */ new Set();
  for (const sample of samples) {
    if (sample.metadata) {
      const value2 = getNestedProperty(sample.metadata, propertyPath);
      if (value2 !== void 0 && value2 !== null) {
        values.add(value2);
      }
    }
  }
  return values;
};
const getNestedProperty = (obj, path) => {
  const keys = path.split(".");
  let current = obj;
  for (const key of keys) {
    if (current && typeof current === "object" && key in current) {
      current = current[key];
    } else {
      return void 0;
    }
  }
  return current;
};
const buildMetadataPath = (tokens, currentTokenIndex) => {
  const parts = [];
  let index = 2;
  while (index <= currentTokenIndex) {
    const token = tokens[currentTokenIndex - index];
    if (token?.text === kSampleMetadataVariable) {
      return parts.reverse().join(".");
    } else if (token?.type === "variable") {
      parts.push(token.text);
      index++;
      if (tokens[currentTokenIndex - index]?.text === ".") {
        index++;
      } else {
        break;
      }
    } else {
      break;
    }
  }
  return null;
};
const getMetadataKeysForPath = (samples, parentPath) => {
  const keys = /* @__PURE__ */ new Set();
  for (const sample of samples) {
    if (sample.metadata) {
      const parentObj = parentPath ? getNestedProperty(sample.metadata, parentPath) : sample.metadata;
      if (parentObj && typeof parentObj === "object" && !Array.isArray(parentObj)) {
        for (const key of Object.keys(parentObj)) {
          keys.add(key);
        }
      }
    }
  }
  return keys;
};
const buildMetadataPropertyPath = (tokens, currentTokenIndex) => {
  const parts = [];
  let index = 2;
  while (index <= currentTokenIndex) {
    const token = tokens[currentTokenIndex - index];
    if (!token) break;
    if (token.type === "variable") {
      if (token.text === kSampleMetadataVariable) {
        return parts.reverse().join(".");
      } else {
        parts.push(token.text);
      }
    } else if (token.text !== ".") {
      break;
    }
    index++;
  }
  return null;
};
const isMetadataProperty = (tokens, currentTokenIndex) => {
  let index = 2;
  while (index <= currentTokenIndex) {
    const token = tokens[currentTokenIndex - index];
    if (!token) break;
    if (token.text === kSampleMetadataVariable) {
      return true;
    } else if (token.text === "." || token.type === "variable") {
      index++;
    } else {
      break;
    }
  }
  return false;
};
const makeMetadataKeyCompletion = (key) => ({
  label: key,
  type: "property",
  info: `Metadata property: ${key}`,
  boost: 25
});
const makeSampleIdCompletion = (id) => ({
  label: typeof id === "string" ? `"${id}"` : String(id),
  type: "text",
  info: `Sample ID: ${id}`,
  boost: 25
});
const makeMetadataValueCompletion = (value2) => {
  let label2;
  if (typeof value2 === "string") {
    label2 = `"${value2}"`;
  } else if (typeof value2 === "boolean") {
    label2 = value2 ? "True" : "False";
  } else if (value2 === null) {
    label2 = "None";
  } else {
    label2 = String(value2);
  }
  return {
    label: label2,
    type: "text",
    info: `Metadata value: ${value2}`,
    boost: 25
  };
};
function getCompletions(context, filterItems, samples) {
  const keywordCompletionItems = KEYWORDS.map(makeKeywordCompletion);
  const mathFunctionCompletionItems = MATH_FUNCTIONS.map(
    makeMathFunctionCompletion
  );
  const sampleFunctionCompletionItems = SAMPLE_FUNCTIONS.map(
    makeSampleFunctionCompletion
  );
  const availableSampleVariables = SAMPLE_VARIABLES.filter(([label2]) => {
    if (label2 === kSampleMetadataVariable) {
      return samples && samples.some(
        (sample) => sample.metadata && Object.keys(sample.metadata).length > 0
      );
    }
    return true;
  });
  const sampleVariableCompletionItems = availableSampleVariables.map(
    makeSampleVariableCompletion
  );
  const variableCompletionItems = filterItems.map(
    (item2) => makeCanonicalNameCompletion(item2)
  );
  const defaultCompletionItems = [
    ...keywordCompletionItems,
    ...mathFunctionCompletionItems,
    ...sampleFunctionCompletionItems,
    ...sampleVariableCompletionItems,
    ...variableCompletionItems
  ];
  const doc = context.state.doc;
  const input2 = doc.toString().slice(0, context.pos);
  const tokens = tokenize(input2);
  const lastToken = tokens[tokens.length - 1];
  const isCompletionInsideToken = lastToken && context.pos === lastToken.to && !autocompleteImmediatelyAfter(lastToken);
  const currentTokenIndex = isCompletionInsideToken ? tokens.length - 1 : tokens.length;
  const prevToken = (index) => tokens[currentTokenIndex - index];
  const currentToken = prevToken(0);
  const completionStart = currentToken ? currentToken.from : context.pos;
  const completingAtEnd = context.pos === doc.length;
  const findFilterItem = (endIndex) => {
    if (prevToken(endIndex)?.type !== "variable") return void 0;
    let name = prevToken(endIndex).text;
    let i = endIndex;
    while (prevToken(i + 1)?.text === ".") {
      if (prevToken(i + 2)?.type === "variable") {
        name = `${prevToken(i + 2).text}.${name}`;
        i += 2;
      } else {
        break;
      }
    }
    return filterItems.find((item2) => item2.canonicalName === name);
  };
  const makeCompletions = (priorityCompletions, {
    autocompleteInTheMiddle = false,
    enforceOrder = false,
    autoSpaceAfter = false,
    includeDefault = true
  } = {}) => {
    if (!autocompleteInTheMiddle && !completingAtEnd && !context.explicit) {
      return null;
    }
    const priorityCompletionsOrdered = enforceOrder ? priorityCompletions.map((c, idx) => ({ ...c, boost: -idx })) : priorityCompletions;
    const priorityCompletionsAdjusted = autoSpaceAfter ? priorityCompletionsOrdered.map(
      (c) => !c.apply && !c.label.endsWith(" ") ? { ...c, label: `${c.label} ` } : c
    ) : priorityCompletionsOrdered;
    if (!includeDefault) {
      return {
        from: completionStart,
        options: priorityCompletionsAdjusted
      };
    }
    const miscSection = {
      name: "misc",
      header: () => {
        const element = document.createElement("hr");
        element.style.display = "list-item";
        element.style.margin = "2px 0";
        return element;
      }
    };
    const priorityLabels = new Set(
      priorityCompletions.map((c) => c.label.trim())
    );
    const defaultCompletionsAdjusted = defaultCompletionItems.filter((c) => !priorityLabels.has(c.label.trim())).map((c) => ({ ...c, section: miscSection }));
    return {
      from: completionStart,
      options: [...priorityCompletionsAdjusted, ...defaultCompletionsAdjusted]
    };
  };
  const defaultCompletions = () => makeCompletions([]);
  const noCompletions = () => context.explicit ? defaultCompletions() : null;
  const newExpressionCompletions = () => makeCompletions([
    ...filterItems.map(
      (item2) => makeCanonicalNameCompletion(item2, {
        autoSpaceIf: (item22) => completingAtEnd && item22.scoreType !== kScoreTypeBoolean
      })
    ),
    ...sampleVariableCompletionItems,
    ...sampleFunctionCompletionItems
  ]);
  const variableCompletions = () => makeCompletions(variableCompletionItems);
  const memberAccessCompletions = (items) => makeCompletions(items.map(makeMemberAccessCompletion), {
    autocompleteInTheMiddle: true,
    includeDefault: false
  });
  const logicalOpCompletions = () => makeCompletions(["and", "or"].map(makeKeywordCompletion), {
    enforceOrder: true,
    autoSpaceAfter: completingAtEnd
  });
  const discreteRelationCompletions = () => makeCompletions(["==", "!=", "in", "not in"].map(makeKeywordCompletion), {
    enforceOrder: true,
    autoSpaceAfter: completingAtEnd
  });
  const continuousRelationCompletions = () => makeCompletions(
    ["<", "<=", ">", ">=", "==", "!="].map(makeKeywordCompletion),
    { enforceOrder: true, autoSpaceAfter: completingAtEnd }
  );
  const customRelationCompletions = () => makeCompletions(
    ["<", "<=", ">", ">=", "==", "!=", "~="].map(makeKeywordCompletion),
    { enforceOrder: true, autoSpaceAfter: completingAtEnd }
  );
  const rhsCompletions = (options) => makeCompletions(options.map(makeLiteralCompletion));
  if (!prevToken(1)) return newExpressionCompletions();
  if (prevToken(1)?.text === ".") {
    const varName = prevToken(2)?.text;
    const metadataPath = buildMetadataPath(tokens, currentTokenIndex);
    if (metadataPath !== null && samples) {
      const metadataKeys = Array.from(
        getMetadataKeysForPath(samples, metadataPath)
      );
      const metadataCompletions = metadataKeys.map(makeMetadataKeyCompletion);
      return makeCompletions(metadataCompletions, {
        autocompleteInTheMiddle: true,
        includeDefault: false
      });
    } else if (varName) {
      return memberAccessCompletions(getMemberScoreItems(filterItems, varName));
    }
  }
  if (prevToken(1)?.text === "(") {
    if (prevToken(2)?.type === "mathFunction") return variableCompletions();
    if (prevToken(2)?.type === "sampleFunction") return noCompletions();
    return newExpressionCompletions();
  }
  if (prevToken(1)?.text === ")") return noCompletions();
  if (prevToken(1)?.type === "variable") {
    const varName = prevToken(1)?.text;
    if (isMetadataProperty(tokens, currentTokenIndex)) {
      return customRelationCompletions();
    }
    if (varName === "epoch") {
      return continuousRelationCompletions();
    }
    if (varName === kSampleIdVariable) {
      return discreteRelationCompletions();
    }
    if (varName === kSampleMetadataVariable) {
      return customRelationCompletions();
    }
    if (varName === "has_error" || varName === "has_retries") {
      return logicalOpCompletions();
    }
    const scoreType = findFilterItem(1)?.scoreType || "";
    switch (scoreType) {
      case kScoreTypePassFail:
      case kScoreTypeCategorical:
        return discreteRelationCompletions();
      case kScoreTypeNumeric:
        return continuousRelationCompletions();
      case kScoreTypeOther:
        return customRelationCompletions();
      case kScoreTypeBoolean:
        return logicalOpCompletions();
      default:
        return noCompletions();
    }
  }
  if (prevToken(1)?.type === "relation") {
    const varName = prevToken(2)?.text;
    const metadataPropertyPath = buildMetadataPropertyPath(
      tokens,
      currentTokenIndex
    );
    if (metadataPropertyPath !== null && samples) {
      const metadataValues = Array.from(
        getMetadataPropertyValues(samples, metadataPropertyPath)
      );
      const currentQuery = currentToken?.text || "";
      const filteredValues = currentQuery ? metadataValues.filter((value2) => {
        const label2 = typeof value2 === "string" ? `"${value2}"` : typeof value2 === "boolean" ? value2 ? "True" : "False" : value2 === null ? "None" : String(value2);
        return label2.toLowerCase().startsWith(currentQuery.toLowerCase());
      }) : metadataValues;
      const metadataValueCompletions = filteredValues.map(
        makeMetadataValueCompletion
      );
      return makeCompletions(metadataValueCompletions, {
        includeDefault: false
      });
    }
    if (varName === kSampleIdVariable && samples) {
      const sampleIds = Array.from(getSampleIds(samples));
      const currentQuery = currentToken?.text || "";
      const filteredIds = currentQuery ? sampleIds.filter((id) => {
        const label2 = typeof id === "string" ? `"${id}"` : String(id);
        return label2.toLowerCase().startsWith(currentQuery.toLowerCase());
      }) : sampleIds;
      const sampleIdCompletions = filteredIds.map(makeSampleIdCompletion);
      return makeCompletions(sampleIdCompletions, {
        includeDefault: false
      });
    }
    if (varName === "epoch" && samples) {
      const epochValues = Array.from(
        new Set(samples.map((s) => s.epoch).filter((e) => e !== void 0))
      ).sort((a, b) => a - b);
      const epochCompletions = epochValues.map(
        (e) => makeLiteralCompletion(String(e))
      );
      return makeCompletions(epochCompletions, {
        includeDefault: epochCompletions.length === 0
      });
    }
    const item2 = findFilterItem(2);
    if (item2?.categories?.length) {
      return rhsCompletions(item2.categories);
    }
    return variableCompletions();
  }
  if (isLiteral(prevToken(1)) && prevToken(2)?.type === "relation") {
    return logicalOpCompletions();
  }
  if (isLogicalOp(prevToken(1))) return newExpressionCompletions();
  return noCompletions();
}
const label$4 = "_label_jbrqc_1";
const input = "_input_jbrqc_7";
const help = "_help_jbrqc_11";
const styles$i = {
  label: label$4,
  input,
  help
};
const FILTER_TOOLTIP = `
Filter samples by:
  • Scores
  • Epoch: e.g. "epoch == 1" or "epoch <= 2"
  • Samples with errors: has_error
  • Input, target and error regex search: input_contains, target_contains, error_contains
  • Samples that have been retried: has_retries
  • Sample Id: e.g. "id == 'sample123'"
  • Sample metadata: e.g. "metadata.key == 'value'"

Supported expressions:
  • Arithmetic: +, -, *, /, mod, ^
  • Comparison: <, <=, >, >=, ==, !=, including chain comparisons, e.g. "10 <= x < 20"
  • Boolean: and, or, not
  • Regex matching: ~= (case-sensitive)
  • Set operations: in, not in; e.g. "x in (2, 3, 5)"
  • Functions: min, max, abs, round, floor, ceil, sqrt, log, log2, log10
`.trim();
const highlightStyle = HighlightStyle.define([
  { tag: tags.string, class: "token string" },
  { tag: tags.number, class: "token number" },
  { tag: tags.keyword, class: "token keyword" }
]);
const editorTheme = EditorView.theme({
  "&": {
    fontSize: "inherit",
    color: "var(--inspect-input-foreground)",
    backgroundColor: "var(--inspect-input-background)",
    border: "1px solid var(--inspect-input-border)",
    borderRadius: "var(--bs-border-radius)"
  },
  ".cm-cursor.cm-cursor-primary": {
    borderLeftColor: "var(--bs-body-color)"
  },
  ".cm-selectionBackground": {
    backgroundColor: "var(--inspect-inactive-selection-background)"
  },
  "&.cm-focused > .cm-scroller > .cm-selectionLayer > .cm-selectionBackground": {
    backgroundColor: "var(--inspect-active-selection-background)"
  },
  "&.cm-focused": {
    outline: "none",
    borderColor: "var(--inspect-focus-border-color)",
    boxShadow: "var(--inspect-focus-border-shadow)"
  },
  ".filter-pending > &.cm-focused": {
    borderColor: "var(--inspect-focus-border-gray-color)",
    boxShadow: "var(--inspect-focus-border-gray-shadow)"
  },
  ".cm-tooltip": {
    backgroundColor: "var(--bs-light)",
    border: "1px solid var(--bs-border-color)",
    color: "var(--bs-body-color)"
  },
  ".cm-tooltip.cm-tooltip-autocomplete > ul > li": {
    color: "var(--bs-body-color)"
  },
  ".cm-tooltip.cm-tooltip-autocomplete > ul > li[aria-selected]": {
    backgroundColor: "var(--inspect-active-selection-background)",
    color: "var(--bs-body-color)"
  },
  ".cm-scroller": {
    overflow: "hidden"
  },
  ".cm-line": {
    "font-size": "var(--inspect-font-size-smallest) !important"
  },
  ".token": {
    "font-size": "var(--inspect-font-size-smallest) !important"
  }
});
const ensureOneLine = (tr) => {
  const newDoc = tr.newDoc.toString();
  if (!newDoc.includes("\n")) return tr;
  if (tr.isUserEvent("input.paste")) {
    return {
      changes: {
        from: 0,
        to: tr.startState.doc.length,
        insert: newDoc.replace(/\n/g, " ").trim()
      }
    };
  }
  return {};
};
const getLints = (view, filterError) => {
  if (!filterError) return [];
  return [
    {
      from: Math.min(filterError.from || 0, view.state.doc.length),
      to: Math.min(
        filterError.to || view.state.doc.length,
        view.state.doc.length
      ),
      severity: filterError.severity,
      message: filterError.message
    }
  ];
};
const SampleFilter = () => {
  const editorRef = reactExports.useRef(null);
  const editorViewRef = reactExports.useRef(null);
  const linterCompartment = reactExports.useRef(new Compartment());
  const autocompletionCompartment = reactExports.useRef(new Compartment());
  const updateListenerCompartment = reactExports.useRef(new Compartment());
  const evalDescriptor = useEvalDescriptor();
  const filterItems = reactExports.useMemo(
    () => evalDescriptor ? sampleFilterItems(evalDescriptor) : [],
    [evalDescriptor]
  );
  const filter = useStore((state) => state.log.filter);
  const filterError = useStore((state) => state.log.filterError);
  const samples = useStore(
    (state) => state.log.selectedLogDetails?.sampleSummaries
  );
  const setFilter = useStore((state) => state.logActions.setFilter);
  const handleFocus = reactExports.useCallback((event, view) => {
    if (event.isTrusted && view.state.doc.toString() === "") {
      setTimeout(() => startCompletion(view), 0);
    }
  }, []);
  const makeAutocompletion = reactExports.useCallback(
    () => autocompletion({
      override: [(context) => getCompletions(context, filterItems, samples)],
      activateOnCompletion: (c) => c.label.endsWith(" ")
    }),
    [filterItems, samples]
  );
  const makeLinter = reactExports.useCallback(
    () => linter((view) => getLints(view, filterError)),
    [filterError]
  );
  const debounceSetFilter = reactExports.useMemo(
    () => debounce((value2) => {
      setFilter(value2);
    }, 200),
    [setFilter]
  );
  const makeUpdateListener = reactExports.useCallback(
    () => EditorView.updateListener.of((update) => {
      if (update.docChanged && evalDescriptor) {
        const newValue = update.state.doc.toString();
        debounceSetFilter(newValue);
      }
    }),
    [debounceSetFilter, evalDescriptor]
  );
  reactExports.useEffect(() => {
    editorViewRef.current?.destroy();
    editorViewRef.current = new EditorView({
      parent: editorRef.current ?? void 0,
      state: EditorState.create({
        doc: filter || "",
        extensions: [
          minimalSetup,
          bracketMatching(),
          editorTheme,
          EditorState.transactionFilter.of(ensureOneLine),
          updateListenerCompartment.current.of(makeUpdateListener()),
          EditorView.domEventHandlers({ focus: handleFocus }),
          language,
          syntaxHighlighting(highlightStyle),
          autocompletionCompartment.current.of(makeAutocompletion()),
          linterCompartment.current.of(makeLinter())
        ]
      })
    });
    return () => editorViewRef.current?.destroy();
  }, []);
  reactExports.useEffect(() => {
    if (!editorViewRef.current) return;
    const currentValue = editorViewRef.current.state.doc.toString();
    if (filter === currentValue) return;
    editorViewRef.current.dispatch({
      changes: {
        from: 0,
        to: currentValue.length,
        insert: filter || ""
      }
    });
  }, [filter]);
  reactExports.useEffect(() => {
    editorViewRef.current?.dispatch({
      effects: updateListenerCompartment.current.reconfigure(makeUpdateListener())
    });
  }, [evalDescriptor, makeUpdateListener]);
  reactExports.useEffect(() => {
    editorViewRef.current?.dispatch({
      effects: autocompletionCompartment.current.reconfigure(makeAutocompletion())
    });
  }, [filterItems, makeAutocompletion, samples]);
  reactExports.useEffect(() => {
    editorViewRef.current?.dispatch({
      effects: linterCompartment.current.reconfigure(makeLinter())
    });
  }, [filterError, makeLinter]);
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex" }, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "span",
      {
        className: clsx(
          "sample-filter-label",
          "text-size-smaller",
          "text-style-label",
          "text-style-secondary",
          styles$i.label
        ),
        children: "Filter:"
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "div",
      {
        ref: editorRef,
        className: clsx(filterError && "filter-pending", styles$i.input)
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "span",
      {
        className: clsx("bi", "bi-question-circle", styles$i.help),
        "data-tooltip": FILTER_TOOLTIP,
        "data-tooltip-position": "bottom-left"
      }
    )
  ] });
};
const container$4 = "_container_uvlpz_1";
const grid$2 = "_grid_uvlpz_5";
const row = "_row_uvlpz_12";
const label$3 = "_label_uvlpz_26";
const links = "_links_uvlpz_32";
const selected = "_selected_uvlpz_50";
const bodyColorButton = "_bodyColorButton_uvlpz_54";
const styles$h = {
  container: container$4,
  grid: grid$2,
  row,
  label: label$3,
  links,
  selected,
  bodyColorButton
};
const SelectScorer = ({
  scores,
  selectedScores,
  setSelectedScores
}) => {
  const [showing, setShowing] = reactExports.useState(false);
  const buttonRef = reactExports.useRef(null);
  const selectedKeys = reactExports.useMemo(() => {
    return new Set(selectedScores?.map((s) => `${s.scorer}.${s.name}`));
  }, [selectedScores]);
  const selectedCount = selectedKeys.size;
  const label2 = selectedCount === 0 ? "Score" : selectedCount === 1 ? selectedScores?.[0]?.name || "Score" : `${selectedCount} Scores`;
  const allScoresSelected = selectedCount === scores.length;
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { display: "flex" }, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "span",
      {
        className: clsx(
          "sample-filter-label",
          "text-size-smaller",
          "text-style-label",
          "text-style-secondary",
          styles$h.label
        ),
        children: "Scorers:"
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      ToolButton,
      {
        label: label2,
        icon: ApplicationIcons.metrics,
        onClick: () => setShowing(!showing),
        ref: buttonRef,
        className: clsx(styles$h.bodyColorButton)
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsxs(
      PopOver,
      {
        id: "score-selector-popover",
        positionEl: buttonRef.current,
        isOpen: showing,
        setIsOpen: setShowing,
        placement: "bottom-start",
        hoverDelay: -1,
        styles: {
          padding: "3px 5px"
        },
        children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$h.links, "text-size-smaller"), children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              "a",
              {
                className: clsx(
                  styles$h.link,
                  !allScoresSelected ? styles$h.selected : void 0
                ),
                onClick: () => {
                  if (scores.length > 0) {
                    setSelectedScores([scores[0]]);
                  }
                },
                children: "Default"
              }
            ),
            "|",
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              "a",
              {
                className: clsx(
                  styles$h.link,
                  allScoresSelected ? styles$h.selected : void 0
                ),
                onClick: () => {
                  setSelectedScores(scores);
                },
                children: "All"
              }
            )
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$h.container, children: /* @__PURE__ */ jsxRuntimeExports.jsx(
            ScoreCheckboxes,
            {
              scores,
              selectedKeys,
              setSelectedScores
            }
          ) })
        ]
      }
    )
  ] });
};
const ScoreCheckboxes = ({
  scores,
  selectedKeys,
  setSelectedScores
}) => {
  const handleToggle = reactExports.useCallback(
    (scoreToToggle, currentlyChecked) => {
      const key = `${scoreToToggle.scorer}.${scoreToToggle.name}`;
      const current = new Set(selectedKeys);
      if (currentlyChecked) {
        current.delete(key);
      } else {
        current.add(key);
      }
      const next = scores.filter((s) => current.has(`${s.scorer}.${s.name}`));
      setSelectedScores(next);
    },
    [setSelectedScores, scores, selectedKeys]
  );
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$h.grid, "text-size-smaller"), children: scores.map((sc) => {
    const key = `${sc.scorer}.${sc.name}`;
    const isChecked = selectedKeys ? selectedKeys.has(key) : false;
    return /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "div",
      {
        className: clsx(styles$h.row),
        onClick: () => handleToggle(sc, isChecked),
        children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "input",
            {
              type: "checkbox",
              checked: isChecked,
              onChange: (e) => {
                e.stopPropagation();
                handleToggle(sc, isChecked);
              }
            }
          ),
          sc.name
        ]
      },
      key
    );
  }) });
};
const SampleTools = () => {
  const scores = useScores();
  const selectedScores = useSelectedScores();
  const setSelectedScores = useStore(
    (state) => state.logActions.setSelectedScores
  );
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(SampleFilter, {}),
    scores?.length > 1 ? /* @__PURE__ */ jsxRuntimeExports.jsx(
      SelectScorer,
      {
        scores,
        selectedScores,
        setSelectedScores
      }
    ) : void 0
  ] });
};
const ScoreFilterTools = () => {
  const scores = useScores();
  const selectedScores = useSelectedScores();
  const setSelectedScores = useStore(
    (state) => state.logActions.setSelectedScores
  );
  if (scores.length <= 1) {
    return void 0;
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    SelectScorer,
    {
      scores,
      selectedScores,
      setSelectedScores
    }
  );
};
const statusCell = "_statusCell_hunte_1";
const error = "_error_hunte_7";
const success = "_success_hunte_11";
const cancelled = "_cancelled_hunte_15";
const styles$g = {
  statusCell,
  error,
  success,
  cancelled
};
const sampleStatus = (completed, error2) => {
  if (error2) {
    return errorType(error2) === "CancelledError" ? "cancelled" : "error";
  }
  return completed ? "ok" : "running";
};
const kDefaultSampleSortValue = "3:ok";
const sampleStatusSortValue = (status2, error2) => {
  switch (status2) {
    case "running":
      return "0:running";
    case "error":
      return `1:error:${errorType(error2)}`;
    case "cancelled":
      return "2:cancelled";
    default:
      return kDefaultSampleSortValue;
  }
};
const SampleStatusIcon = ({ status: status2 }) => {
  if (status2 === "running") {
    return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$g.statusCell, children: /* @__PURE__ */ jsxRuntimeExports.jsx(PulsingDots, { subtle: false }) });
  }
  const icon2 = status2 === "error" ? ApplicationIcons.error : status2 === "cancelled" ? ApplicationIcons.cancelled : ApplicationIcons.success;
  const colorClass = status2 === "error" ? styles$g.error : status2 === "cancelled" ? styles$g.cancelled : styles$g.success;
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$g.statusCell, children: /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: clsx(icon2, colorClass) }) });
};
const mainLayout = "_mainLayout_1s8x3_1";
const samplesListGrid = "_samplesListGrid_1s8x3_7";
const cell = "_cell_1s8x3_44";
const wrapAnywhere = "_wrapAnywhere_1s8x3_48";
const noLeft = "_noLeft_1s8x3_52";
const score = "_score_1s8x3_56";
const centered = "_centered_1s8x3_63";
const styles$f = {
  mainLayout,
  samplesListGrid,
  cell,
  wrapAnywhere,
  noLeft,
  score,
  centered
};
const ScoreCellDiv = ({ children }) => /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-size-small", styles$f.cell, styles$f.score), children });
const MarkdownCellDiv = ({ semanticClass, text: text2, trimRenderedText }) => {
  const markdown = truncateMarkdown(text2, 250);
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    "div",
    {
      className: clsx(
        semanticClass,
        "text-size-base",
        "three-line-clamp",
        styles$f.cell,
        styles$f.wrapAnywhere
      ),
      children: /* @__PURE__ */ jsxRuntimeExports.jsx(
        RenderedText,
        {
          markdown,
          className: trimRenderedText ? clsx("no-last-para-padding", styles$f.noLeft) : void 0,
          forceRender: true,
          omitMedia: true
        }
      )
    }
  );
};
function buildColumnDefs(samplesDescriptor, selectedScores, scores, epochs) {
  const shape = samplesDescriptor?.messageShape;
  const inputFlex = shape?.inputSize || 3;
  const targetFlex = shape?.targetSize || 1;
  const answerFlex = shape?.answerSize || 1;
  const scoreLabels = !selectedScores || selectedScores.length === 0 ? [] : scores && scores.length === 1 ? ["Score"] : selectedScores?.map((s) => s.name) ?? [];
  const columns = [
    {
      colId: "sampleStatus",
      headerName: "",
      headerTooltipValueGetter: () => "Sample Status",
      width: 24,
      valueGetter: (params) => {
        if (!params.data) return kDefaultSampleSortValue;
        const s = sampleStatus(params.data.completed, params.data.data.error);
        return sampleStatusSortValue(s, params.data.data.error);
      },
      cellRenderer: (params) => {
        if (!params.data) return null;
        const s = sampleStatus(params.data.completed, params.data.data.error);
        return /* @__PURE__ */ jsxRuntimeExports.jsx(SampleStatusIcon, { status: s });
      },
      tooltipValueGetter: (params) => {
        if (!params.data) return null;
        return params.data.data.error ? params.data.data.error : sampleStatus(params.data.completed, params.data.data.error);
      }
    },
    {
      colId: "id",
      headerName: "Id",
      width: (shape?.idSize ?? 2) * 16,
      // 16 for 1em in pixels
      minWidth: 35,
      valueGetter: (params) => params.data?.data?.id,
      cellRenderer: (params) => {
        if (!params.data) return null;
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          "div",
          {
            className: clsx(
              "sample-id",
              "text-size-base",
              "three-line-clamp",
              styles$f.cell,
              styles$f.wrapAnywhere
            ),
            children: params.data.data.id
          }
        );
      }
    },
    {
      colId: "epoch",
      headerName: "Epoch",
      width: 50,
      minWidth: 28,
      hide: epochs <= 1,
      valueGetter: (params) => params.data?.data?.epoch,
      cellRenderer: (params) => {
        if (!params.data) return null;
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          "div",
          {
            className: clsx(
              "sample-epoch",
              "text-size-base",
              styles$f.cell,
              styles$f.centered
            ),
            children: params.data.data.epoch
          }
        );
      }
    },
    {
      colId: "input",
      headerName: "Input",
      flex: inputFlex,
      minWidth: 80,
      hide: !shape?.inputSize,
      valueGetter: (params) => {
        return params.data ? inputString(params.data.data.input).join(" ") : "";
      },
      cellRenderer: (params) => {
        if (!params.data) return null;
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          MarkdownCellDiv,
          {
            semanticClass: "sample-input",
            text: inputString(params.data.data.input).join(" ")
          }
        );
      }
    },
    {
      colId: "target",
      headerName: "Target",
      flex: targetFlex,
      minWidth: 80,
      hide: !shape?.targetSize,
      valueGetter: (params) => {
        return params.data?.data?.target != null ? arrayToString(params.data.data.target) : "";
      },
      cellRenderer: (params) => {
        if (!params.data?.data?.target) return null;
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          MarkdownCellDiv,
          {
            semanticClass: "sample-target",
            text: arrayToString(params.data.data.target),
            trimRenderedText: true
          }
        );
      }
    },
    {
      colId: "answer",
      headerName: "Answer",
      flex: answerFlex,
      minWidth: 80,
      hide: !shape?.answerSize,
      valueGetter: (params) => params.data?.answer ?? "",
      cellRenderer: (params) => {
        if (!params.data) return null;
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          MarkdownCellDiv,
          {
            semanticClass: "sample-answer",
            text: params.data.answer || "",
            trimRenderedText: true
          }
        );
      }
    },
    {
      colId: "limit",
      headerName: "Limit",
      width: (shape?.limitSize ?? 1) * 16,
      minWidth: 28,
      hide: !shape?.limitSize,
      valueGetter: (params) => params.data?.data?.limit,
      cellRenderer: (params) => {
        if (!params.data) return null;
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          "div",
          {
            className: clsx(
              "sample-limit",
              "text-size-small",
              "three-line-clamp",
              styles$f.cell,
              styles$f.wrapAnywhere
            ),
            children: params.data.data.limit
          }
        );
      }
    },
    {
      colId: "retries",
      headerName: "Retries",
      width: (shape?.retriesSize ?? 1) * 16,
      minWidth: 28,
      hide: !shape?.retriesSize,
      valueGetter: (params) => params.data?.data?.retries,
      cellRenderer: (params) => {
        if (!params.data) return null;
        const { data } = params.data;
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          "div",
          {
            className: clsx(
              "sample-retries",
              "text-size-small",
              "three-line-clamp",
              styles$f.cell,
              styles$f.centered
            ),
            children: data.retries && data.retries > 0 ? data.retries : void 0
          }
        );
      }
    }
  ];
  scoreLabels.forEach((label2, i) => {
    columns.push({
      headerName: label2,
      colId: `score-${i}`,
      width: 80,
      minWidth: 28,
      valueGetter: (params) => {
        if (!params.data?.data || !samplesDescriptor) return void 0;
        return samplesDescriptor.evalDescriptor.score(
          params.data.data,
          selectedScores[i]
        )?.value;
      },
      cellRenderer: (params) => {
        if (!params.data) return null;
        const { data, completed } = params.data;
        const rendered = samplesDescriptor?.evalDescriptor.score(data, selectedScores[i])?.render();
        if (completed && rendered !== void 0) {
          return /* @__PURE__ */ jsxRuntimeExports.jsx(ScoreCellDiv, { children: rendered });
        }
        return /* @__PURE__ */ jsxRuntimeExports.jsx(ScoreCellDiv, {});
      }
    });
  });
  return columns;
}
const footer = "_footer_vkofn_1";
const spinnerContainer = "_spinnerContainer_vkofn_11";
const spinner$1 = "_spinner_vkofn_11";
const label$2 = "_label_vkofn_25";
const styles$e = {
  footer,
  spinnerContainer,
  spinner: spinner$1,
  label: label$2
};
const SampleFooter = ({
  sampleCount,
  totalSampleCount,
  running
}) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx("text-size-smaller", styles$e.footer), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: running ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$e.spinnerContainer), children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "div",
        {
          className: clsx("spinner-border", styles$e.spinner),
          role: "status",
          children: /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: clsx("visually-hidden"), children: "Running..." })
        }
      ),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-style-secondary", styles$e.label), children: "running..." })
    ] }) : void 0 }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: sampleCount < totalSampleCount ? `${sampleCount} / ${totalSampleCount} Samples` : `${sampleCount} Samples` })
  ] });
};
const kSampleHeight = 88;
const makeSampleRowId = (id, epoch) => `${id}-${epoch}`.replace(/\s+/g, "_");
const SampleList = reactExports.memo((props) => {
  const {
    items,
    earlyStopping,
    totalItemCount,
    running,
    className,
    listHandle
  } = props;
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  reactExports.useEffect(() => {
    listHandle.current?.api?.ensureIndexVisible(0, "top");
  }, [listHandle, selectedLogFile]);
  const sampleNavigation = useSampleNavigation();
  const selectedSampleHandle = useStore(
    (state) => state.log.selectedSampleHandle
  );
  const selectedLogDetails = useStore((state) => state.log.selectedLogDetails);
  const evalSpec = selectedLogDetails?.eval;
  const epochs = evalSpec?.config?.epochs || 1;
  const { setDocumentTitle } = useDocumentTitle();
  reactExports.useEffect(() => {
    setDocumentTitle({ evalSpec });
  }, [setDocumentTitle, evalSpec]);
  const followOutputRef = reactExports.useRef(running);
  const prevItemCountRef = reactExports.useRef(items.length);
  reactExports.useEffect(() => {
    if (running) {
      followOutputRef.current = true;
    }
  }, [running]);
  reactExports.useEffect(() => {
    if (running && followOutputRef.current && items.length > prevItemCountRef.current && listHandle.current?.api) {
      listHandle.current.api.ensureIndexVisible(items.length - 1, "bottom");
    }
    prevItemCountRef.current = items.length;
  }, [items.length, running, listHandle]);
  const handleBodyScroll = reactExports.useCallback(() => {
    if (!running || !listHandle.current?.api) return;
    const api2 = listHandle.current.api;
    const vPixel = api2.getVerticalPixelRange();
    const totalHeight = api2.getDisplayedRowCount() * kSampleHeight;
    const viewportHeight = vPixel.bottom - vPixel.top;
    const atBottom = vPixel.bottom >= totalHeight - viewportHeight * 0.1;
    followOutputRef.current = atBottom;
  }, [running, listHandle]);
  const prevRunningRef = reactExports.useRef(running);
  reactExports.useEffect(() => {
    if (!running && prevRunningRef.current && listHandle.current?.api) {
      followOutputRef.current = false;
      setTimeout(() => {
        listHandle.current?.api?.ensureIndexVisible(0, "top");
      }, 100);
    }
    prevRunningRef.current = running;
  }, [running, listHandle]);
  const handleRowClick = reactExports.useCallback(
    (e) => {
      if (e.data && e.node && listHandle.current?.api) {
        listHandle.current.api.deselectAll();
        e.node.setSelected(true);
        const mouseEvent = e.event;
        const openInNewWindow = mouseEvent?.metaKey || mouseEvent?.ctrlKey || mouseEvent?.shiftKey || mouseEvent?.button === 1;
        if (openInNewWindow) {
          const url = sampleNavigation.getSampleUrl(
            e.data.data.id,
            e.data.data.epoch
          );
          if (url) window.open(url, "_blank");
        } else {
          sampleNavigation.showSample(e.data.data.id, e.data.data.epoch);
        }
      }
    },
    [sampleNavigation, listHandle]
  );
  const handleOpenRow = reactExports.useCallback(
    (rowNode, _e) => {
      if (rowNode.data) {
        sampleNavigation.showSample(
          rowNode.data.data.id,
          rowNode.data.data.epoch
        );
      }
    },
    [sampleNavigation]
  );
  const gridContainerRef = reactExports.useRef(null);
  const handleKeyDown = reactExports.useMemo(
    () => createGridKeyboardHandler({
      gridRef: listHandle,
      onOpenRow: handleOpenRow
    }),
    [listHandle, handleOpenRow]
  );
  reactExports.useEffect(() => {
    const el = gridContainerRef.current;
    if (!el) return;
    const handler = handleKeyDown;
    el.addEventListener("keydown", handler);
    return () => el.removeEventListener("keydown", handler);
  }, [handleKeyDown]);
  const selectCurrentSample = reactExports.useCallback(() => {
    if (!listHandle.current?.api || !selectedSampleHandle) {
      return;
    }
    const rowId = makeSampleRowId(
      selectedSampleHandle.id,
      selectedSampleHandle.epoch
    );
    const node = listHandle.current.api.getRowNode(rowId);
    if (node) {
      listHandle.current.api.deselectAll();
      node.setSelected(true);
      listHandle.current.api.ensureNodeVisible(node, "middle");
    }
  }, [listHandle, selectedSampleHandle]);
  reactExports.useEffect(() => {
    selectCurrentSample();
  }, [selectedSampleHandle, selectCurrentSample]);
  const selectedScores = useSelectedScores();
  const scores = useScores();
  const samplesDescriptor = useSampleDescriptor();
  const columnDefs = reactExports.useMemo(
    () => buildColumnDefs(samplesDescriptor, selectedScores, scores, epochs),
    [samplesDescriptor, selectedScores, scores, epochs]
  );
  const getRowId = reactExports.useCallback((params) => {
    return makeSampleRowId(params.data.data.id, params.data.data.epoch);
  }, []);
  const manuallyResized = reactExports.useRef(/* @__PURE__ */ new Set());
  const handleColumnResized = reactExports.useCallback(
    (event) => {
      if (event.finished && event.source === "uiColumnResized" && event.column) {
        manuallyResized.current.add(event.column.getColId());
        const state = columnDefs.filter(
          (c) => c.colId && c.flex && !manuallyResized.current.has(c.colId)
        ).map((c) => ({ colId: c.colId, flex: c.flex }));
        if (state.length > 0) {
          listHandle.current?.api?.applyColumnState({ state });
        }
      }
    },
    [listHandle, columnDefs]
  );
  const sampleCount = items.length;
  const warnings = reactExports.useMemo(() => {
    const errorCount = items.reduce(
      (prev, item2) => item2.data.error ? prev + 1 : prev,
      0
    );
    const limitCount = items.reduce(
      (prev, item2) => item2.data.limit ? prev + 1 : prev,
      0
    );
    const percentError = sampleCount > 0 ? errorCount / sampleCount * 100 : 0;
    const percentLimit = sampleCount > 0 ? limitCount / sampleCount * 100 : 0;
    const result = [];
    if (errorCount > 0) {
      result.push({
        type: "info",
        msg: `INFO: ${errorCount} of ${sampleCount} samples (${formatNoDecimal(percentError)}%) had errors and were not scored.`
      });
    }
    if (limitCount > 0) {
      result.push({
        type: "info",
        msg: `INFO: ${limitCount} of ${sampleCount} samples (${formatNoDecimal(percentLimit)}%) completed due to exceeding a limit.`
      });
    }
    if (earlyStopping?.early_stops && earlyStopping?.early_stops?.length > 0) {
      result.push({
        type: "info",
        msg: `Skipped ${earlyStopping.early_stops.length} samples due to early stopping (${earlyStopping.manager}). `
      });
    }
    return result;
  }, [items, sampleCount, earlyStopping]);
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: styles$f.mainLayout, children: [
    warnings.map((warning, index) => /* @__PURE__ */ jsxRuntimeExports.jsx(
      MessageBand,
      {
        id: `sample-warning-message-${index}`,
        message: warning.msg,
        type: warning.type
      },
      `sample-warning-message-${index}`
    )),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "div",
      {
        ref: gridContainerRef,
        className: clsx(className, styles$f.samplesListGrid, "samples-list"),
        style: {
          flex: 1,
          minHeight: 0,
          display: "flex",
          flexDirection: "column"
        },
        tabIndex: 0,
        children: /* @__PURE__ */ jsxRuntimeExports.jsx(
          AgGridReact,
          {
            ref: listHandle,
            rowData: items,
            columnDefs,
            defaultColDef: {
              filter: false,
              headerTooltipValueGetter: (params) => params.colDef?.headerName
            },
            tooltipShowDelay: 300,
            animateRows: false,
            rowHeight: kSampleHeight,
            headerHeight: 25,
            getRowId,
            rowSelection: { mode: "singleRow", checkboxes: false },
            onRowClicked: handleRowClick,
            onColumnResized: handleColumnResized,
            theme: themeBalham,
            enableCellTextSelection: true,
            suppressCellFocus: true,
            domLayout: "normal",
            onBodyScroll: handleBodyScroll,
            onFirstDataRendered: () => {
              if (running && followOutputRef.current) {
                listHandle.current?.api?.ensureIndexVisible(
                  items.length - 1,
                  "bottom"
                );
              }
              selectCurrentSample();
            }
          }
        )
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      SampleFooter,
      {
        sampleCount,
        totalSampleCount: totalItemCount,
        running
      }
    )
  ] });
});
const panel = "_panel_1yknn_1";
const container$3 = "_container_1yknn_7";
const spinner = "_spinner_1yknn_14";
const text = "_text_1yknn_20";
const styles$d = {
  panel,
  container: container$3,
  spinner,
  text
};
const RunningNoSamples = () => {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$d.panel), children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$d.container, "text-size-smaller"), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$d.spinner, "spinner-border"), role: "status", children: /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: clsx("visually-hidden"), children: "starting..." }) }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$d.text), children: "starting...." })
  ] }) });
};
const useSamplesTabConfig = (evalStatus, refreshLog) => {
  const totalSampleCount = useTotalSampleCount();
  const samplesDescriptor = useSampleDescriptor();
  const streamSamples = useStore((state) => state.capabilities.streamSamples);
  return reactExports.useMemo(() => {
    return {
      id: kLogViewSamplesTabId,
      scrollable: false,
      label: totalSampleCount > 1 ? "Samples" : "Sample",
      component: SamplesTab,
      componentProps: {
        running: evalStatus === "started"
      },
      tools: () => !samplesDescriptor ? void 0 : totalSampleCount === 1 ? [/* @__PURE__ */ jsxRuntimeExports.jsx(ScoreFilterTools, {}, "sample-score-tool")] : [
        /* @__PURE__ */ jsxRuntimeExports.jsx(SampleTools, {}, "sample-tools"),
        evalStatus === "started" && !streamSamples && /* @__PURE__ */ jsxRuntimeExports.jsx(
          ToolButton,
          {
            label: "Refresh",
            icon: ApplicationIcons.refresh,
            onClick: refreshLog
          },
          "refresh"
        )
      ]
    };
  }, [
    evalStatus,
    refreshLog,
    samplesDescriptor,
    streamSamples,
    totalSampleCount
  ]);
};
const SamplesTab = ({ running }) => {
  const sampleSummaries = useFilteredSamples();
  const selectedLogDetails = useStore((state) => state.log.selectedLogDetails);
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  const evalSampleCount = reactExports.useMemo(() => {
    const limit = selectedLogDetails?.eval.config.limit;
    const limitCount = limit === null || limit === void 0 ? void 0 : typeof limit === "number" ? limit : limit[1] - limit[0];
    return (limitCount || selectedLogDetails?.eval.dataset.samples || 0) * (selectedLogDetails?.eval.config.epochs || 0);
  }, [
    selectedLogDetails?.eval.config.epochs,
    selectedLogDetails?.eval.config.limit,
    selectedLogDetails?.eval.dataset.samples
  ]);
  const totalSampleCount = useTotalSampleCount();
  const samplesDescriptor = useSampleDescriptor();
  const selectSample = useStore((state) => state.logActions.selectSample);
  const sampleStatus2 = useStore((state) => state.sample.sampleStatus);
  const sampleListHandle = reactExports.useRef(null);
  const items = reactExports.useMemo(() => {
    if (!samplesDescriptor) return [];
    return sampleSummaries.map(
      (sample) => ({
        data: sample,
        answer: samplesDescriptor.selectedScorerDescriptor(sample)?.answer() || "",
        completed: sample.completed !== void 0 ? sample.completed : true
      })
    );
  }, [sampleSummaries, samplesDescriptor]);
  reactExports.useEffect(() => {
    if (sampleSummaries.length === 1 && selectedLogFile) {
      const sample = sampleSummaries[0];
      selectSample(sample.id, sample.epoch, selectedLogFile);
    }
  }, [sampleSummaries, selectSample, selectedLogFile]);
  if (totalSampleCount === 0) {
    if (running) {
      return /* @__PURE__ */ jsxRuntimeExports.jsx(RunningNoSamples, {});
    } else {
      return /* @__PURE__ */ jsxRuntimeExports.jsx(NoContentsPanel, { text: "No samples" });
    }
  } else {
    return /* @__PURE__ */ jsxRuntimeExports.jsxs(reactExports.Fragment, { children: [
      samplesDescriptor && totalSampleCount === 1 ? /* @__PURE__ */ jsxRuntimeExports.jsx(InlineSampleDisplay, { showActivity: sampleStatus2 === "loading" }) : void 0,
      samplesDescriptor && totalSampleCount > 1 ? /* @__PURE__ */ jsxRuntimeExports.jsx(
        SampleList,
        {
          listHandle: sampleListHandle,
          items,
          earlyStopping: selectedLogDetails?.results?.early_stopping,
          totalItemCount: evalSampleCount,
          running
        }
      ) : void 0
    ] });
  }
};
const ghCommitUrl = (origin, commit) => {
  const baseUrl2 = origin.replace(/\.git$/, "").replace(/^git@github.com:/, "https://github.com/");
  return `${baseUrl2}/commit/${commit}`;
};
const grid$1 = "_grid_er9fb_1";
const styles$c = {
  grid: grid$1
};
const useTaskTabConfig = (evalSpec, evalStats, earlyStopping) => {
  return reactExports.useMemo(() => {
    return {
      id: kLogViewTaskTabId,
      label: "Task",
      scrollable: true,
      component: TaskTab,
      componentProps: {
        evalSpec,
        evalStats,
        earlyStopping
      }
    };
  }, [evalSpec, evalStats, earlyStopping]);
};
const TaskTab = ({
  evalSpec,
  evalStats,
  earlyStopping
}) => {
  Object.entries(evalSpec?.config || {}).forEach((entry) => {
    entry[0];
    entry[1];
  });
  const revision = evalSpec?.revision;
  const packages = evalSpec?.packages;
  const taskInformation = {
    ["Task ID"]: evalSpec?.task_id,
    ["Run ID"]: evalSpec?.run_id
  };
  if (revision) {
    taskInformation[`${revision.type ? `${toTitleCase(revision.type)} ` : ""}Revision`] = {
      _html: /* @__PURE__ */ jsxRuntimeExports.jsx("a", { href: ghCommitUrl(revision.origin, revision.commit), children: revision.commit })
    };
  }
  if (packages) {
    const names = Object.keys(packages).map((key) => {
      return `${key} ${packages[key]}`;
    });
    if (names.length === 1) {
      taskInformation["Inspect"] = names[0];
    } else {
      taskInformation["Inspect"] = names;
    }
  }
  if (evalSpec?.tags) {
    taskInformation["tags"] = evalSpec?.tags.join(", ");
  }
  if (evalSpec?.sandbox) {
    if (Array.isArray(evalSpec?.sandbox)) {
      taskInformation["sandbox"] = evalSpec.sandbox[0];
      if (evalSpec.sandbox[1]) {
        taskInformation["sandbox_config"] = evalSpec.sandbox[1];
      }
    } else {
      taskInformation["sandbox"] = evalSpec?.sandbox.type;
      taskInformation["sandbox_config"] = evalSpec?.sandbox.config;
    }
  }
  const totalDuration = formatDuration(
    new Date(evalStats?.started_at || 0),
    new Date(evalStats?.completed_at || 0)
  );
  const task_args = evalSpec?.task_args || {};
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { style: { width: "100%" }, children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { padding: "0.5em 1em 0 1em", width: "100%" }, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs(Card, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(CardHeader, { label: "Task Info" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(CardBody, { id: "task-card-config", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$c.grid), children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          MetaDataGrid,
          {
            className: "text-size-small",
            entries: taskInformation
          },
          `plan-md-task`
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          MetaDataGrid,
          {
            entries: {
              ["Start"]: formatDateTime(
                new Date(evalStats?.started_at || 0)
              ),
              ["End"]: formatDateTime(
                new Date(evalStats?.completed_at || 0)
              ),
              ["Duration"]: totalDuration
            }
          }
        )
      ] }) })
    ] }),
    earlyStopping && /* @__PURE__ */ jsxRuntimeExports.jsxs(Card, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        CardHeader,
        {
          label: `Early Stopping (${earlyStopping.manager} — ${formatNumber(earlyStopping.early_stops.length)} skipped)`
        }
      ),
      /* @__PURE__ */ jsxRuntimeExports.jsx(CardBody, { children: /* @__PURE__ */ jsxRuntimeExports.jsx(
        RecordTree,
        {
          id: `early-stopping-metadata`,
          record: earlyStopping.metadata
        }
      ) })
    ] }),
    Object.keys(task_args).length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsxs(Card, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(CardHeader, { label: "Task Args" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(CardBody, { id: "task-card-config", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
        MetaDataGrid,
        {
          className: "text-size-small",
          entries: task_args
        },
        `plan-md-task-args`
      ) })
    ] })
  ] }) });
};
const downloadLogButton = "_downloadLogButton_fi3zx_1";
const styles$b = {
  downloadLogButton
};
const DownloadLogButton = ({
  log_file,
  className = "",
  ariaLabel = "Download log as EVAL"
}) => {
  const [downloadState, setDownloadState] = reactExports.useState("idle");
  const api2 = useStore((state) => state.api);
  const handleClick = async () => {
    if (!api2?.download_log) return;
    setDownloadState("downloading");
    try {
      await api2.download_log(log_file);
      setDownloadState("success");
    } catch (error2) {
      console.error("Failed to download log:", error2);
      setDownloadState("error");
    } finally {
      setTimeout(() => {
        setDownloadState("idle");
      }, 1250);
    }
  };
  const getIcon = () => {
    switch (downloadState) {
      case "downloading":
        return ApplicationIcons.loading;
      case "success":
        return ApplicationIcons.confirm;
      case "error":
        return ApplicationIcons.error;
      default:
        return ApplicationIcons.downloadLog;
    }
  };
  const getIconClass = () => {
    const icon2 = getIcon();
    if (downloadState === "success") {
      return `${icon2} primary`;
    }
    if (downloadState === "error") {
      return `${icon2} text-danger`;
    }
    return icon2;
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    "button",
    {
      type: "button",
      className: clsx(
        "download-log-button",
        styles$b.downloadLogButton,
        className
      ),
      onClick: handleClick,
      "aria-label": ariaLabel,
      disabled: downloadState !== "idle",
      children: /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: getIconClass(), "aria-hidden": "true" })
    }
  );
};
const metricDisplayName = (metric) => {
  let modifier = void 0;
  for (const metricModifier of metricModifiers) {
    modifier = metricModifier(metric);
    if (modifier) {
      break;
    }
  }
  const metricName = !modifier ? metric.name : `${metric.name}[${modifier}]`;
  return metricName;
};
const clusterMetricModifier = (metric) => {
  if (metric.name !== "stderr") {
    return void 0;
  }
  const clusterValue = (metric.params || {})["cluster"];
  if (clusterValue === void 0 || typeof clusterValue !== "string") {
    return void 0;
  }
  return clusterValue;
};
const groupMetricModifier = (metric) => {
  const groupKey = (metric.params || {})["group_key"];
  if (groupKey === void 0 || typeof groupKey !== "string") {
    return void 0;
  }
  const metricRaw = (metric.params || {})["metric"];
  if (metricRaw === void 0 || typeof metricRaw !== "object") {
    return void 0;
  }
  const metricObj = metricRaw;
  const name = metricObj["name"];
  return name;
};
const metricModifiers = [
  clusterMetricModifier,
  groupMetricModifier
];
const toDisplayScorers = (scores) => {
  if (!scores) {
    return [];
  }
  return scores.map((score2) => {
    return {
      scorer: score2.name,
      reducer: score2.reducer === null ? void 0 : score2.reducer,
      metrics: Object.keys(score2.metrics).map((key) => {
        const metric = score2.metrics[key];
        return {
          name: metric.name,
          value: metric.value,
          params: metric.params
        };
      }),
      unscoredSamples: score2.unscored_samples !== null ? score2.unscored_samples : void 0,
      scoredSamples: score2.scored_samples !== null ? score2.scored_samples : void 0
    };
  });
};
const isGroupedMetric = (metric) => {
  if (!metric.params) {
    return false;
  }
  const params = metric.params;
  return params["group_key"] !== void 0 && params["metric"] !== void 0;
};
const getBaseMetricName = (metric) => {
  if (!metric.params) {
    return void 0;
  }
  const params = metric.params;
  const metricObj = params["metric"];
  if (!metricObj || typeof metricObj !== "object") {
    return void 0;
  }
  return metricObj["name"];
};
const normalizeMetricName = (name) => {
  return name.replace(/\d+$/, "");
};
const expandGroupedMetrics = (scorers) => {
  const result = [];
  for (const scorer2 of scorers) {
    if (scorer2.metrics.length === 0) {
      result.push(scorer2);
      continue;
    }
    const hasGroupedMetrics = scorer2.metrics.some(isGroupedMetric);
    if (!hasGroupedMetrics) {
      result.push(scorer2);
      continue;
    }
    const metricsByBase = /* @__PURE__ */ new Map();
    const nonGroupedMetrics = [];
    for (const metric of scorer2.metrics) {
      const baseMetricName = getBaseMetricName(metric);
      if (!baseMetricName) {
        nonGroupedMetrics.push(metric);
        continue;
      }
      if (!metricsByBase.has(baseMetricName)) {
        metricsByBase.set(baseMetricName, []);
      }
      metricsByBase.get(baseMetricName).push({
        ...metric,
        name: normalizeMetricName(metric.name)
      });
    }
    if (nonGroupedMetrics.length > 0) {
      result.push({
        scorer: scorer2.scorer,
        reducer: scorer2.reducer,
        metrics: nonGroupedMetrics,
        unscoredSamples: scorer2.unscoredSamples,
        scoredSamples: scorer2.scoredSamples
      });
    }
    for (const [baseMetricName, metrics] of metricsByBase.entries()) {
      result.push({
        scorer: scorer2.scorer,
        reducer: baseMetricName,
        metrics,
        unscoredSamples: scorer2.unscoredSamples,
        scoredSamples: scorer2.scoredSamples
      });
    }
  }
  return result;
};
const container$2 = "_container_q17yq_1";
const grid = "_grid_q17yq_10";
const styles$a = {
  container: container$2,
  grid
};
const ModelRolesView = ({ roles }) => {
  roles = roles || {};
  const singleLine = Object.keys(roles).length !== 1;
  const modelEls = Object.keys(roles).map((key) => {
    const role2 = key;
    const roleData = roles[role2];
    const model = roleData.model;
    return /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "div",
      {
        className: clsx(
          singleLine ? styles$a.grid : void 0,
          "text-style-secondary",
          "text-size-smallest"
        ),
        children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: clsx("text-style-label"), children: [
            role2,
            ":"
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: model })
        ]
      },
      key
    );
  });
  return modelEls.length > 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$a.container, children: modelEls }) : void 0;
};
const container$1 = "_container_17txe_1";
const wrapper = "_wrapper_17txe_8";
const body = "_body_17txe_21";
const bodyContainer = "_bodyContainer_17txe_27";
const taskTitle = "_taskTitle_17txe_33";
const taskModel = "_taskModel_17txe_38";
const taskStatus = "_taskStatus_17txe_42";
const secondaryContainer = "_secondaryContainer_17txe_49";
const buttonGroup = "_buttonGroup_17txe_58";
const styles$9 = {
  container: container$1,
  wrapper,
  body,
  bodyContainer,
  taskTitle,
  taskModel,
  taskStatus,
  secondaryContainer,
  buttonGroup
};
const button = "_button_12472_1";
const label$1 = "_label_12472_14";
const styles$8 = {
  button,
  label: label$1
};
const LinkButton = ({
  id,
  text: text2,
  icon: icon2,
  className,
  onClick
}) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(
    "button",
    {
      id,
      onClick,
      className: clsx(className, styles$8.button, "text-size-smaller"),
      children: [
        icon2 ? /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: clsx(icon2) }) : void 0,
        text2 ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$8.label), children: text2 }) : void 0
      ]
    }
  );
};
const modal = "_modal_o64lp_1";
const header = "_header_o64lp_14";
const modalTitle = "_modalTitle_o64lp_18";
const btnClose = "_btnClose_o64lp_22";
const backdrop = "_backdrop_o64lp_28";
const overflowVisible = "_overflowVisible_o64lp_40";
const overflowHidden = "_overflowHidden_o64lp_44";
const overflowScroll = "_overflowScroll_o64lp_48";
const overflowAuto = "_overflowAuto_o64lp_52";
const styles$7 = {
  modal,
  header,
  modalTitle,
  btnClose,
  backdrop,
  overflowVisible,
  overflowHidden,
  overflowScroll,
  overflowAuto
};
const Modal = ({
  id,
  title,
  showing,
  setShowing,
  children,
  className,
  overflow = "visible"
}) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
    showing && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$7.backdrop, onClick: () => setShowing(false) }),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "div",
      {
        id,
        className: clsx("modal", "fade", showing ? "show" : "", className),
        tabIndex: -1,
        style: { display: showing ? "block" : "none" },
        children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("modal-dialog", styles$7.modal), children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "modal-content", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx("modal-header", styles$7.header), children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              "div",
              {
                className: clsx(
                  "modal-title",
                  "text-size-base",
                  styles$7.modalTitle
                ),
                children: title
              }
            ),
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              "button",
              {
                type: "button",
                className: clsx(
                  "btn-close",
                  "text-size-smaller",
                  styles$7.btnClose
                ),
                "data-bs-dismiss": "modal",
                "aria-label": "Close",
                onClick: () => {
                  setShowing(!showing);
                }
              }
            )
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "div",
            {
              className: clsx(
                "modal-body",
                overflow === "auto" ? styles$7.overflowAuto : overflow === "hidden" ? styles$7.overflowHidden : overflow === "scroll" ? styles$7.overflowScroll : styles$7.overflowVisible
              ),
              children
            }
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "modal-footer", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
            "button",
            {
              type: "button",
              className: "btn btn-secondary",
              "data-bs-dismiss": "modal",
              onClick: () => {
                setShowing(!showing);
              },
              children: "Close"
            }
          ) })
        ] }) })
      }
    )
  ] });
};
const groupScorers = (scorers) => {
  const results = {};
  scorers.forEach((scorer2) => {
    if (scorer2.metrics.length > 0) {
      const key = metricsKey(scorer2.metrics);
      results[key] = results[key] || [];
      results[key].push(scorer2);
    }
  });
  return Object.values(results);
};
const metricsKey = (metrics) => {
  const metricKey = metrics.map((m) => m.name).join("");
  return metricKey;
};
const simpleMetricsRows = "_simpleMetricsRows_1itqo_1";
const verticalMetricReducer = "_verticalMetricReducer_1itqo_26";
const verticalMetricName = "_verticalMetricName_1itqo_33";
const verticalMetricValue = "_verticalMetricValue_1itqo_41";
const moreButton = "_moreButton_1itqo_91";
const metricsSummary = "_metricsSummary_1itqo_97";
const modalScores = "_modalScores_1itqo_104";
const styles$6 = {
  simpleMetricsRows,
  verticalMetricReducer,
  verticalMetricName,
  verticalMetricValue,
  moreButton,
  metricsSummary,
  modalScores
};
const table = "_table_12koy_1";
const scorer = "_scorer_12koy_5";
const value = "_value_12koy_6";
const label = "_label_12koy_11";
const groupSeparator = "_groupSeparator_12koy_28";
const tableBody = "_tableBody_12koy_33";
const tableSeparator = "_tableSeparator_12koy_45";
const styles$5 = {
  table,
  scorer,
  value,
  label,
  groupSeparator,
  tableBody,
  tableSeparator
};
const unscoredSamples = "_unscoredSamples_1h85z_1";
const styles$4 = {
  unscoredSamples
};
const UnscoredSamples = ({
  scoredSamples,
  unscoredSamples: unscoredSamples2
}) => {
  if (unscoredSamples2 === 0) {
    return null;
  }
  const msg = unscoredSamples2 === 1 ? `${unscoredSamples2} sample was excluded from this metric because it returned a Nan value.` : `${unscoredSamples2} samples were excluded from this metric because they returned Nan values.`;
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(
    "span",
    {
      className: clsx("text-style-secondary", styles$4.unscoredSamples),
      title: msg,
      children: [
        "(",
        scoredSamples,
        "/",
        unscoredSamples2 + scoredSamples,
        ")"
      ]
    }
  );
};
const ScoreGrid = ({
  scoreGroups,
  showReducer,
  className,
  striped
}) => {
  const columnCount = scoreGroups.reduce((prev, group) => {
    return Math.max(prev, group[0].metrics.length);
  }, 0);
  const subTables = [];
  let index = 0;
  for (const scoreGroup of scoreGroups) {
    const metrics = scoreGroup[0].metrics;
    const cells = [];
    for (let i = 0; i < columnCount; i++) {
      if (metrics.length > i) {
        cells.push(
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "th",
            {
              className: clsx(
                "text-style-label",
                "text-style-secondary",
                "text-size-small",
                styles$5.label
              ),
              children: metrics[i].name
            }
          )
        );
      } else {
        cells.push(/* @__PURE__ */ jsxRuntimeExports.jsx("td", {}));
      }
    }
    const headerRow = /* @__PURE__ */ jsxRuntimeExports.jsx("thead", { children: /* @__PURE__ */ jsxRuntimeExports.jsxs("tr", { className: clsx(styles$5.headerRow), children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("td", {}),
      cells
    ] }) });
    const rows = [];
    scoreGroup.forEach((g) => {
      const cells2 = [];
      for (let i = 0; i < columnCount; i++) {
        if (metrics.length > i) {
          cells2.push(
            /* @__PURE__ */ jsxRuntimeExports.jsx("td", { className: clsx(styles$5.value, "text-size-small"), children: formatPrettyDecimal(g.metrics[i].value) })
          );
        } else {
          cells2.push(/* @__PURE__ */ jsxRuntimeExports.jsx("td", { className: clsx(styles$5.value) }));
        }
      }
      rows.push(
        /* @__PURE__ */ jsxRuntimeExports.jsxs("tr", { children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("th", { className: clsx(styles$5.scorer, "text-size-small"), children: [
            g.scorer,
            " ",
            showReducer && g.reducer ? `(${g.reducer})` : void 0,
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              UnscoredSamples,
              {
                scoredSamples: g.scoredSamples || 0,
                unscoredSamples: g.unscoredSamples || 0
              }
            )
          ] }),
          cells2
        ] })
      );
    });
    subTables.push(
      /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
        index > 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx("tbody", { className: clsx(styles$5.tableSeparator), children: /* @__PURE__ */ jsxRuntimeExports.jsx("tr", { children: /* @__PURE__ */ jsxRuntimeExports.jsx(
          "td",
          {
            colSpan: columnCount + 1,
            className: clsx(styles$5.groupSeparator)
          }
        ) }) }) : void 0,
        headerRow,
        /* @__PURE__ */ jsxRuntimeExports.jsx("tbody", { className: clsx("table-group-divider", styles$5.tableBody), children: rows })
      ] })
    );
    index++;
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    "table",
    {
      className: clsx(
        className,
        "table",
        striped ? "table-striped" : void 0,
        styles$5.table,
        "table-bordered"
      ),
      children: subTables
    }
  );
};
const kMaxPrimaryScoreRows = 4;
const displayScorersFromRunningMetrics = (metrics) => {
  if (!metrics) {
    return [];
  }
  const getKey = (metric) => {
    return metric.reducer ? `${metric.scorer}-${metric.reducer}` : metric.scorer;
  };
  const scorers = {};
  metrics.forEach((metric) => {
    if (metric.value !== void 0 && metric.value !== null) {
      const key = getKey(metric);
      if (scorers[key]) {
        scorers[key].metrics.push({
          name: metric.name,
          value: metric.value,
          params: metric.params
        });
      } else {
        scorers[key] = {
          scorer: metric.scorer,
          reducer: metric.reducer,
          metrics: [
            {
              name: metric.name,
              value: metric.value,
              params: metric.params
            }
          ]
        };
      }
    }
  });
  return expandGroupedMetrics(Object.values(scorers));
};
const ResultsPanel = ({ scorers }) => {
  const [showing, setShowing] = useProperty(
    "results-panel-metrics",
    "modal-showing",
    {
      defaultValue: false
    }
  );
  if (!scorers || scorers.length === 0) {
    return void 0;
  }
  const expandedScorers = expandGroupedMetrics(scorers);
  if (expandedScorers.length === 1) {
    const showReducer = !!expandedScorers[0].reducer;
    const metrics = expandedScorers[0].metrics;
    const unscoredSamples2 = expandedScorers[0].unscoredSamples || 0;
    const scoredSamples = expandedScorers[0].scoredSamples || 0;
    return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$6.simpleMetricsRows, children: metrics.map((metric, i) => {
      return /* @__PURE__ */ jsxRuntimeExports.jsx(
        VerticalMetric,
        {
          reducer: expandedScorers[0].reducer,
          metric,
          isFirst: i === 0,
          showReducer,
          unscoredSamples: unscoredSamples2,
          scoredSamples
        },
        `simple-metric-${i}`
      );
    }) });
  } else {
    const showReducer = expandedScorers.findIndex((score2) => !!score2.reducer) !== -1;
    const grouped = groupScorers(expandedScorers);
    if (grouped.length < 1) {
      return void 0;
    }
    let primaryResults = grouped[0];
    if (!primaryResults) {
      return void 0;
    }
    let showMore = grouped.length > 1;
    if (primaryResults.length > kMaxPrimaryScoreRows) {
      const shorterResults = grouped.find((g) => {
        return g.length <= kMaxPrimaryScoreRows;
      });
      if (shorterResults) {
        primaryResults = shorterResults;
      }
      if (primaryResults.length > kMaxPrimaryScoreRows) {
        primaryResults = primaryResults.slice(0, kMaxPrimaryScoreRows);
        showMore = true;
      }
    }
    return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$6.metricsSummary), children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(ScoreGrid, { scoreGroups: [primaryResults], showReducer }),
      showMore ? /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          Modal,
          {
            id: "results-metrics",
            showing,
            setShowing,
            title: "Scoring Detail",
            overflow: "scroll",
            children: /* @__PURE__ */ jsxRuntimeExports.jsx(
              ScoreGrid,
              {
                scoreGroups: grouped,
                showReducer,
                className: styles$6.modalScores,
                striped: false
              }
            )
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          LinkButton,
          {
            className: styles$6.moreButton,
            text: "All scoring...",
            onClick: () => {
              setShowing(true);
            }
          }
        )
      ] }) : void 0
    ] });
  }
};
const VerticalMetric = ({
  metric,
  reducer,
  isFirst,
  showReducer,
  scoredSamples,
  unscoredSamples: unscoredSamples2
}) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { style: { paddingLeft: isFirst ? "0" : "1em" }, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "div",
      {
        className: clsx(
          "vertical-metric-label",
          "text-style-label",
          "text-style-secondary",
          styles$6.verticalMetricName
        ),
        children: [
          metricDisplayName(metric),
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            UnscoredSamples,
            {
              scoredSamples,
              unscoredSamples: unscoredSamples2
            }
          )
        ]
      }
    ),
    showReducer ? /* @__PURE__ */ jsxRuntimeExports.jsx(
      "div",
      {
        className: clsx(
          "text-style-label",
          "text-style-secondary",
          styles$6.verticalMetricReducer
        ),
        children: reducer || "default"
      }
    ) : void 0,
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "div",
      {
        className: clsx(
          "vertical-metric-value",
          "text-size-largest",
          styles$6.verticalMetricValue
        ),
        children: metric.value !== void 0 && metric.value !== null ? formatPrettyDecimal(metric.value) : "n/a"
      }
    )
  ] });
};
const statusContainer = "_statusContainer_1sckj_1";
const status = "_status_1sckj_1";
const statusText = "_statusText_1sckj_11";
const icon = "_icon_1sckj_24";
const styles$3 = {
  statusContainer,
  status,
  statusText,
  icon
};
const RunningStatusPanel = ({ sampleCount }) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$3.statusContainer), children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$3.status), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: clsx(ApplicationIcons.running, styles$3.icon) }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "div",
      {
        className: clsx(
          styles$3.statusText,
          "text-style-label",
          "text-size-smaller"
        ),
        children: [
          "Running (",
          sampleCount,
          " samples)"
        ]
      }
    )
  ] }) }) });
};
const statusPanel = "_statusPanel_1o5l7_1";
const statusIcon = "_statusIcon_1o5l7_11";
const styles$2 = {
  statusPanel,
  statusIcon
};
const CancelledPanel = ({ sampleCount }) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    StatusPanel,
    {
      icon: ApplicationIcons.logging["info"],
      status: "Cancelled",
      sampleCount
    }
  );
};
const ErroredPanel = ({ sampleCount }) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    StatusPanel,
    {
      icon: ApplicationIcons.logging["error"],
      status: "Task Failed",
      sampleCount
    }
  );
};
const StatusPanel = ({
  icon: icon2,
  status: status2,
  sampleCount
}) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: styles$2.statusPanel, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: clsx(icon2, styles$2.statusIcon), style: {} }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: status2 }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
        "(",
        sampleCount,
        " ",
        sampleCount === 1 ? "sample" : "samples",
        ")"
      ] })
    ] })
  ] });
};
const PrimaryBar = ({
  status: status2,
  evalResults,
  runningMetrics,
  evalSpec,
  sampleCount
}) => {
  const streamSamples = useStore((state) => state.capabilities.streamSamples);
  const downloadLogs = useStore((state) => state.capabilities.downloadLogs);
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  const logFileName = selectedLogFile ? filename(selectedLogFile) : "";
  const isEvalFile = selectedLogFile?.endsWith(".eval");
  const hasRunningMetrics = runningMetrics && runningMetrics.length > 0;
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$9.wrapper), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "div",
      {
        className: clsx(
          "navbar-brand",
          "navbar-text",
          "mb-0",
          styles$9.container
        ),
        children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: styles$9.body, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: styles$9.bodyContainer, children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              "div",
              {
                id: "task-title",
                className: clsx("task-title", "text-truncate", styles$9.taskTitle),
                title: evalSpec?.task,
                children: evalSpec?.task
              }
            ),
            evalSpec?.model && evalSpec.model !== kModelNone ? /* @__PURE__ */ jsxRuntimeExports.jsx(
              "div",
              {
                id: "task-model",
                className: clsx(
                  "task-model",
                  "text-truncate",
                  styles$9.taskModel,
                  "text-size-base"
                ),
                title: evalSpec?.model,
                children: evalSpec?.model
              }
            ) : ""
          ] }),
          evalSpec?.model_roles ? /* @__PURE__ */ jsxRuntimeExports.jsx(ModelRolesView, { roles: evalSpec.model_roles }) : void 0,
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx("text-size-small", styles$9.secondaryContainer), children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("navbar-secondary-text", "text-truncate"), children: logFileName }),
            /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: styles$9.buttonGroup, children: [
              selectedLogFile ? /* @__PURE__ */ jsxRuntimeExports.jsx(CopyButton, { value: selectedLogFile }) : "",
              downloadLogs && selectedLogFile && isEvalFile ? /* @__PURE__ */ jsxRuntimeExports.jsx(DownloadLogButton, { log_file: selectedLogFile }) : null
            ] })
          ] })
        ] })
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$9.taskStatus, "navbar-text"), children: [
      status2 === "success" || status2 === "started" && streamSamples && hasRunningMetrics || status2 === "error" && evalSpec?.config["continue_on_fail"] ? /* @__PURE__ */ jsxRuntimeExports.jsx(
        ResultsPanel,
        {
          scorers: runningMetrics ? displayScorersFromRunningMetrics(runningMetrics) : toDisplayScorers(evalResults?.scores)
        }
      ) : void 0,
      status2 === "cancelled" ? /* @__PURE__ */ jsxRuntimeExports.jsx(CancelledPanel, { sampleCount: sampleCount || 0 }) : void 0,
      status2 === "started" && (!streamSamples || !hasRunningMetrics) ? /* @__PURE__ */ jsxRuntimeExports.jsx(RunningStatusPanel, { sampleCount: sampleCount || 0 }) : void 0,
      status2 === "error" ? /* @__PURE__ */ jsxRuntimeExports.jsx(ErroredPanel, { sampleCount: sampleCount || 0 }) : void 0
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { id: "task-created", style: { display: "none" }, children: evalSpec?.created })
  ] });
};
const staticCol = "_staticCol_qgv1z_1";
const justifyLeft = "_justifyLeft_qgv1z_5";
const justifyCenter = "_justifyCenter_qgv1z_9";
const justifyRight = "_justifyRight_qgv1z_13";
const valueGrid = "_valueGrid_qgv1z_17";
const container = "_container_qgv1z_25";
const invalidationStatus = "_invalidationStatus_qgv1z_30";
const styles$1 = {
  staticCol,
  justifyLeft,
  justifyCenter,
  justifyRight,
  valueGrid,
  container,
  invalidationStatus
};
const SecondaryBar = ({
  evalSpec,
  evalPlan,
  evalResults,
  evalStats,
  status: status2,
  sampleCount
}) => {
  const evalDescriptor = useEvalDescriptor();
  const [sampleInvalidation] = useSampleInvalidation();
  if (!evalSpec || status2 !== "success") {
    return null;
  }
  const epochs = evalSpec.config.epochs || 1;
  const hyperparameters = {
    ...evalPlan?.config || {},
    ...evalSpec.task_args || {}
  };
  const hasConfig = Object.keys(hyperparameters).length > 0;
  const values = [];
  values.push({
    size: "minmax(12%, auto)",
    value: /* @__PURE__ */ jsxRuntimeExports.jsx(
      LabeledValue,
      {
        label: "Dataset",
        className: clsx(styles$1.staticCol, "text-size-small"),
        children: /* @__PURE__ */ jsxRuntimeExports.jsx(
          DatasetSummary,
          {
            dataset: evalSpec.dataset,
            sampleCount,
            epochs
          }
        )
      },
      "sb-dataset"
    )
  });
  const label2 = evalResults?.scores && evalResults.scores.length > 1 ? "Scorers" : "Scorer";
  values.push({
    size: "minmax(12%, auto)",
    value: /* @__PURE__ */ jsxRuntimeExports.jsx(
      LabeledValue,
      {
        label: label2,
        className: clsx(
          styles$1.staticCol,
          hasConfig ? styles$1.justifyLeft : styles$1.justifyCenter,
          "text-size-small"
        ),
        children: /* @__PURE__ */ jsxRuntimeExports.jsx(ScorerSummary, { evalDescriptor })
      },
      "sb-scorer"
    )
  });
  if (hasConfig) {
    values.push({
      size: "minmax(12%, auto)",
      value: /* @__PURE__ */ jsxRuntimeExports.jsx(
        LabeledValue,
        {
          label: "Config",
          className: clsx(styles$1.justifyRight, "text-size-small"),
          children: /* @__PURE__ */ jsxRuntimeExports.jsx(ParamSummary, { params: hyperparameters })
        },
        "sb-params"
      )
    });
  }
  if (evalStats) {
    const totalDuration = formatDuration(
      new Date(evalStats?.started_at),
      new Date(evalStats?.completed_at)
    );
    values.push({
      size: "minmax(12%, auto)",
      value: /* @__PURE__ */ jsxRuntimeExports.jsx(
        LabeledValue,
        {
          label: "Duration",
          className: clsx(styles$1.justifyRight, "text-size-small"),
          children: totalDuration
        },
        "sb-duration"
      )
    });
  }
  if (sampleInvalidation) {
    values.push({
      size: "minmax(12%, auto)",
      value: /* @__PURE__ */ jsxRuntimeExports.jsx(
        InvalidationStatus,
        {
          invalidation: sampleInvalidation
        },
        "sb-invalidation"
      )
    });
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    ExpandablePanel,
    {
      id: "secondary-nav-bar",
      className: clsx(styles$1.container, "text-size-small"),
      collapse: true,
      lines: 5,
      children: /* @__PURE__ */ jsxRuntimeExports.jsx(
        "div",
        {
          className: styles$1.valueGrid,
          style: {
            gridTemplateColumns: `${values.map((val) => {
              return val.size;
            }).join(" ")}`
          },
          children: values.map((val) => {
            return val.value;
          })
        }
      )
    }
  );
};
const DatasetSummary = ({
  sampleCount,
  dataset,
  epochs
}) => {
  if (!dataset) {
    return null;
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: sampleCount ? formatDataset(sampleCount, epochs, dataset.name) : "" });
};
const ScorerSummary = ({ evalDescriptor }) => {
  if (!evalDescriptor) {
    return null;
  }
  const items = sampleFilterItems(evalDescriptor);
  return /* @__PURE__ */ jsxRuntimeExports.jsx("span", { style: { position: "relative" }, children: Array.from(items).map((item2, index, array) => /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { title: item2.tooltip, children: item2.canonicalName }),
    index < array.length - 1 ? ", " : ""
  ] }, index)) });
};
const ParamSummary = ({ params }) => {
  if (!params) {
    return null;
  }
  const paraValues = Object.keys(params).map((key) => {
    const val = params[key];
    if (Array.isArray(val) || typeof val === "object") {
      return `${key}: ${JSON.stringify(val)}`;
    } else {
      return `${key}: ${val}`;
    }
  });
  if (paraValues.length > 0) {
    return /* @__PURE__ */ jsxRuntimeExports.jsx(
      "code",
      {
        style: {
          padding: 0,
          color: "var(--bs-body-color)",
          overflowWrap: "anywhere"
        },
        children: paraValues.join(", ")
      }
    );
  } else {
    return null;
  }
};
const InvalidationStatus = ({ invalidation }) => {
  const formatTimestamp = (timestamp) => {
    try {
      return formatDateTime(new Date(timestamp));
    } catch {
      return timestamp;
    }
  };
  const details = [
    invalidation.author && `By: ${invalidation.author}`,
    invalidation.timestamp && `On: ${formatTimestamp(invalidation.timestamp)}`,
    invalidation.reason && `Reason: ${invalidation.reason}`
  ].filter(Boolean).join(" · ");
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    LabeledValue,
    {
      label: "Status",
      className: clsx(styles$1.justifyRight, "text-size-small"),
      children: /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: styles$1.invalidationStatus, title: details, children: "⚠ Invalidated" })
    }
  );
};
const navbarWrapper = "_navbarWrapper_838qu_48";
const styles = {
  navbarWrapper
};
const TitleView = ({
  evalSpec,
  evalPlan,
  evalResults,
  evalStats,
  status: status2,
  runningMetrics
}) => {
  const totalSampleCount = useTotalSampleCount();
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("nav", { className: clsx("navbar", "sticky-top", styles.navbarWrapper), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      PrimaryBar,
      {
        evalSpec,
        evalResults,
        status: status2,
        runningMetrics,
        sampleCount: totalSampleCount
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      SecondaryBar,
      {
        evalSpec,
        evalPlan,
        evalResults,
        evalStats,
        status: status2,
        sampleCount: totalSampleCount
      }
    )
  ] });
};
const LogView = () => {
  const divRef = reactExports.useRef(null);
  const refreshLog = useRefreshLog();
  const navigation = useLogNavigation();
  const selectedLogDetails = useStore((state) => state.log.selectedLogDetails);
  const evalSpec = useEvalSpec();
  const runningMetrics = useStore(
    (state) => state.log.pendingSampleSummaries?.metrics
  );
  const samplesTabConfig = useSamplesTabConfig(
    selectedLogDetails?.status,
    refreshLog
  );
  const intoTabConfig = useInfoTabConfig(
    evalSpec,
    selectedLogDetails?.plan,
    selectedLogDetails?.error,
    selectedLogDetails?.results,
    selectedLogDetails?.status
  );
  const errorTabConfig = useErrorTabConfig(selectedLogDetails?.error);
  const taskTabConfig = useTaskTabConfig(
    evalSpec,
    selectedLogDetails?.stats,
    selectedLogDetails?.results?.early_stopping
  );
  const modelsTabConfig = useModelsTab(
    evalSpec,
    selectedLogDetails?.stats,
    selectedLogDetails?.status
  );
  const jsonTabConfig = useJsonTabConfig(
    selectedLogDetails?.version,
    selectedLogDetails?.status,
    evalSpec,
    selectedLogDetails?.plan,
    selectedLogDetails?.error,
    selectedLogDetails?.results,
    selectedLogDetails?.stats
  );
  const tabs2 = {
    ...samplesTabConfig ? { samples: samplesTabConfig } : {},
    task: taskTabConfig,
    model: modelsTabConfig,
    config: intoTabConfig,
    ...selectedLogDetails?.error ? { error: errorTabConfig } : {},
    json: jsonTabConfig
  };
  const selectedTab = useStore((state) => state.app.tabs.workspace);
  const setSelectedTab = useStore((state) => state.appActions.setWorkspaceTab);
  const onSelected = reactExports.useCallback(
    (e) => {
      const id = e.currentTarget?.id;
      if (id) {
        setSelectedTab(id);
        navigation.selectTab(id);
      }
    },
    [setSelectedTab, navigation]
  );
  if (evalSpec === void 0) {
    return /* @__PURE__ */ jsxRuntimeExports.jsx(EmptyPanel, {});
  } else {
    const tabTools = Object.keys(tabs2).map((key) => {
      const tab = tabs2[key];
      return tab;
    }).filter((tab) => {
      return tab.id === selectedTab;
    }).map((tab) => {
      if (tab.tools) {
        const tools = tab.tools();
        return tools;
      } else {
        return null;
      }
    });
    return /* @__PURE__ */ jsxRuntimeExports.jsxs(reactExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        TitleView,
        {
          evalSpec,
          evalPlan: selectedLogDetails?.plan,
          evalResults: selectedLogDetails?.results,
          runningMetrics,
          evalStats: selectedLogDetails?.stats,
          status: selectedLogDetails?.status
        }
      ),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { ref: divRef, className: clsx("workspace", styles$s.workspace), children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("log-detail", styles$s.tabContainer), children: /* @__PURE__ */ jsxRuntimeExports.jsx(
        TabSet,
        {
          id: "log-details",
          tools: tabTools,
          type: "pills",
          className: clsx(styles$s.tabSet, "text-size-smaller"),
          tabControlsClassName: clsx(styles$s.tabs, "text-size-smaller"),
          tabPanelsClassName: clsx(styles$s.tabPanels),
          children: Object.keys(tabs2).map((key) => {
            const tab = tabs2[key];
            return /* @__PURE__ */ jsxRuntimeExports.jsx(
              TabPanel,
              {
                id: tab.id,
                title: tab.label,
                onSelected,
                selected: selectedTab === tab.id,
                scrollable: !!tab.scrollable,
                scrollRef: tab.scrollRef,
                className: clsx(tab.className),
                style: { height: tab.scrollable ? "100%" : void 0 },
                children: reactExports.createElement(tab.component, tab.componentProps)
              },
              tab.id
            );
          })
        }
      ) }) })
    ] });
  }
};
const LogViewLayout = () => {
  const appStatus = useStore((state) => state.app.status);
  const showFind = useStore((state) => state.app.showFind);
  const setShowFind = useStore((state) => state.appActions.setShowFind);
  const nativeFind = useStore((state) => state.app.nativeFind);
  const hideFind = useStore((state) => state.appActions.hideFind);
  const singleFileMode = useStore((state) => state.app.singleFileMode);
  const logDir = useStore((state) => state.logs.logDir);
  const logFiles = useStore((state) => state.logs.logs);
  const { logPath } = useLogRouteParams();
  const mainAppRef = reactExports.useRef(null);
  const fullScreen = logFiles.length === 1 && !logDir;
  reactExports.useEffect(() => {
    if (nativeFind) {
      return;
    }
    const handleGlobalKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        e.preventDefault();
        e.stopPropagation();
        if (setShowFind) {
          setShowFind(true);
        }
      } else if (e.key === "Escape") {
        hideFind();
      }
    };
    document.addEventListener("keydown", handleGlobalKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleGlobalKeyDown, true);
    };
  }, [setShowFind, hideFind, nativeFind]);
  return /* @__PURE__ */ jsxRuntimeExports.jsx(ExtendedFindProvider, { children: /* @__PURE__ */ jsxRuntimeExports.jsxs(
    "div",
    {
      ref: mainAppRef,
      className: clsx(
        "app-main-grid",
        fullScreen ? "full-screen" : void 0,
        singleFileMode ? "single-file-mode" : void 0,
        "log-view"
      ),
      tabIndex: 0,
      children: [
        showFind ? /* @__PURE__ */ jsxRuntimeExports.jsx(FindBand, {}) : "",
        !singleFileMode ? /* @__PURE__ */ jsxRuntimeExports.jsx(
          ApplicationNavbar,
          {
            fnNavigationUrl: logsUrl,
            currentPath: logPath,
            showActivity: "log"
          }
        ) : /* @__PURE__ */ jsxRuntimeExports.jsx(ActivityBar, { animating: !!appStatus.loading }),
        appStatus.error ? /* @__PURE__ */ jsxRuntimeExports.jsx(
          ErrorPanel,
          {
            title: "An error occurred while loading this task.",
            error: appStatus.error
          }
        ) : /* @__PURE__ */ jsxRuntimeExports.jsx(LogView, {})
      ]
    }
  ) });
};
const LogViewContainer = () => {
  const { logPath, tabId, sampleUuid, sampleTabId } = useLogRouteParams();
  const initialState = useStore((state) => state.app.initialState);
  const clearInitialState = useStore(
    (state) => state.appActions.clearInitialState
  );
  const evalSpec = useEvalSpec();
  const setWorkspaceTab = useStore((state) => state.appActions.setWorkspaceTab);
  const setSelectedLogFile = useStore(
    (state) => state.logsActions.setSelectedLogFile
  );
  const clearSelectedLogSummary = useStore(
    (state) => state.logActions.clearSelectedLogDetails
  );
  const clearSelectedSample = useStore(
    (state) => state.sampleActions.clearSelectedSample
  );
  const navigate = useNavigate();
  const sampleSummaries = useSampleSummaries();
  const [searchParams] = useSearchParams();
  const { unloadLog } = useUnloadLog();
  reactExports.useEffect(() => {
    return () => {
      unloadLog();
    };
  }, [unloadLog]);
  reactExports.useEffect(() => {
    if (logPath && sampleUuid && sampleSummaries) {
      const sample = sampleSummaries.find((s) => s.uuid === sampleUuid);
      if (sample) {
        const url = logSamplesUrl(
          logPath,
          sample.id,
          sample.epoch,
          sampleTabId
        );
        const finalUrl = searchParams.toString() ? `${url}?${searchParams.toString()}` : url;
        navigate(finalUrl);
        return;
      }
    }
  }, [
    sampleSummaries,
    logPath,
    sampleUuid,
    searchParams,
    sampleTabId,
    navigate
  ]);
  reactExports.useEffect(() => {
    if (initialState && !evalSpec) {
      const url = baseUrl(
        initialState.log,
        initialState.sample_id,
        initialState.sample_epoch
      );
      clearInitialState();
      navigate(url);
    }
  }, [initialState, evalSpec, clearInitialState, navigate]);
  const prevLogPath = usePrevious(logPath);
  const syncLogs = useStore((state) => state.logsActions.syncLogs);
  const initLogDir = useStore((state) => state.logsActions.initLogDir);
  reactExports.useEffect(() => {
    const loadLogFromPath = async () => {
      if (logPath) {
        await initLogDir();
        setSelectedLogFile(logPath);
        void syncLogs();
        if (tabId) {
          setWorkspaceTab(tabId);
        } else {
          setWorkspaceTab(kLogViewSamplesTabId);
        }
        if (prevLogPath && logPath !== prevLogPath) {
          clearSelectedSample();
          clearSelectedLogSummary();
        }
      }
    };
    loadLogFromPath();
  }, [
    logPath,
    tabId,
    setSelectedLogFile,
    setWorkspaceTab,
    initLogDir,
    syncLogs,
    prevLogPath,
    clearSelectedSample,
    clearSelectedLogSummary
  ]);
  return /* @__PURE__ */ jsxRuntimeExports.jsx(LogViewLayout, {});
};
export {
  LogViewContainer
};
//# sourceMappingURL=LogViewContainer.js.map
