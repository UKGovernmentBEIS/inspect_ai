import "bootstrap/dist/css/bootstrap.css";
import "bootstrap-icons/font/bootstrap-icons.css";
import "prismjs/themes/prism.css";
import "prismjs";
import "../App.css";

import { default as ClipboardJS } from "clipboard";
// @ts-ignore
import { Offcanvas } from "bootstrap";
import { html } from "htm/preact";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "preact/hooks";

// Registration component
import "./Register.mjs";

import { sleep } from "./utils/sync.mjs";
import { clearDocumentSelection } from "./components/Browser.mjs";
import { AppErrorBoundary } from "./components/AppErrorBoundary.mjs";
import { ErrorPanel } from "./components/ErrorPanel.mjs";
import { ProgressBar } from "./components/ProgressBar.mjs";

import { Sidebar } from "./sidebar/Sidebar.mjs";
import { WorkSpace } from "./workspace/WorkSpace.mjs";
import { FindBand } from "./components/FindBand.mjs";
import { isVscode } from "./utils/Html.mjs";
import { getVscodeApi } from "./utils/vscode.mjs";
import { kDefaultSort } from "./constants.mjs";
import { createsSamplesDescriptor } from "./samples/SamplesDescriptor.mjs";
import { byEpoch, bySample, sortSamples } from "./samples/tools/SortFilter.mjs";
import { resolveAttachments } from "./utils/attachments.mjs";
import { filterFnForType } from "./samples/tools/filters.mjs";

import {
  kEvalWorkspaceTabId,
  kInfoWorkspaceTabId,
  kSampleMessagesTabId,
  kSampleTranscriptTabId,
} from "./constants.mjs";

/**
 * Renders the Main Application
 *
 * @param {Object} props - The parameters for the component.
 * @param {import("./api/Types.mjs").ClientAPI} props.api - The api that this view should use
 * @param {Object} [props.initialState] - Initial state for app (optional, used by VS Code extension)
 * @param {(state: Object) => void} [props.saveInitialState] - Save initial state for app (optional, used by VS Code extension)
 * @param {boolean} props.pollForLogs - Whether the application should poll for log changes
 * @returns {import("preact").JSX.Element} The App component.
 */
export function App({
  api,
  initialState = undefined,
  saveInitialState = undefined,
  pollForLogs = true,
}) {
  // List of Logs
  const [logs, setLogs] = useState(
    initialState?.logs || { log_dir: "", files: [] },
  );
  const [selectedLogIndex, setSelectedLogIndex] = useState(
    initialState?.selectedLogIndex !== undefined
      ? initialState.selectedLogIndex
      : -1,
  );

  // Log Headers
  const [logHeaders, setLogHeaders] = useState(initialState?.logHeaders || {});
  const [headersLoading, setHeadersLoading] = useState(
    initialState?.headersLoading || false,
  );

  // Selected Log
  const [selectedLog, setSelectedLog] = useState(
    initialState?.selectedLog || {
      contents: undefined,
      name: undefined,
    },
  );

  // Workspace (the selected tab)
  const [selectedWorkspaceTab, setSelectedWorkspaceTab] = useState(
    initialState?.selectedWorkspaceTab || kEvalWorkspaceTabId,
  );

  // Samples
  const [selectedSampleIndex, setSelectedSampleIndex] = useState(
    initialState?.selectedSampleIndex !== undefined
      ? initialState.selectedSampleIndex
      : -1,
  );
  const [selectedSample, setSelectedSample] = useState(
    initialState?.selectedSample,
  );
  const [sampleStatus, setSampleStatus] = useState(initialState?.sampleStatus);
  const [sampleError, setSampleError] = useState(initialState?.sampleError);
  const [selectedSampleTab, setSelectedSampleTab] = useState(
    initialState?.selectedSampleTab,
  );

  const loadingSampleIndexRef = useRef(null);

  const [showingSampleDialog, setShowingSampleDialog] = useState(
    initialState?.showingSampleDialog,
  );

  // App loading status
  const [status, setStatus] = useState(
    initialState?.status || {
      loading: true,
      error: undefined,
    },
  );

  // App host capabilities
  const [capabilities, setCapabilities] = useState(
    initialState?.capabilities || {
      downloadFiles: true,
      webWorkers: true,
    },
  );

  // Other application state
  const [offcanvas, setOffcanvas] = useState(initialState?.offcanvas || false);
  const [showFind, setShowFind] = useState(initialState?.showFind || false);

  // Filtering and sorting
  /**
   * @type {[import("./Types.mjs").ScoreFilter, function(import("./Types.mjs").ScoreFilter): void]}
   */
  const [filter, setFilter] = useState(initialState?.filter || {});

  /**
   * @type {[string, function(string): void]}
   */
  const [epoch, setEpoch] = useState(initialState?.epoch || "all");

  /**
   * @type {[string, function(string): void]}
   */
  const [sort, setSort] = useState(initialState?.sort || kDefaultSort);

  /**
   * @type {[import("./Types.mjs").ScoreLabel[], function(import("./Types.mjs").ScoreLabel[]): void]}
   */
  const [scores, setScores] = useState(initialState?.scores || []);

  /**
   * @type {[import("./Types.mjs").ScoreLabel, function(import("./Types.mjs").ScoreLabel): void]}
   */
  const [score, setScore] = useState(initialState?.score);

  // Re-filter the samples
  const [filteredSamples, setFilteredSamples] = useState(
    initialState?.filteredSamples || [],
  );
  const [groupBy, setGroupBy] = useState(initialState?.groupBy || "none");
  const [groupByOrder, setGroupByOrder] = useState(
    initialState?.groupByOrder || "asc",
  );

  const afterBodyElements = [];

  /** @type {import("./Types.mjs").RenderContext} */
  const context = {
    afterBody: (el) => {
      afterBodyElements.push(el);
    },
  };

  // Save state when it changes, so that we can restore it later
  //
  useEffect(() => {
    const state = {
      logs,
      selectedLogIndex,
      logHeaders,
      headersLoading,
      selectedLog,
      selectedSampleIndex,
      selectedWorkspaceTab,
      selectedSample,
      sampleStatus,
      sampleError,
      selectedSampleTab,
      showingSampleDialog,
      status,
      capabilities,
      offcanvas,
      showFind,
      filter,
      epoch,
      sort,
      scores,
      score,
      filteredSamples,
      groupBy,
      groupByOrder,
    };
    if (saveInitialState) {
      saveInitialState(state);
    }
  }, [
    logs,
    selectedLogIndex,
    logHeaders,
    headersLoading,
    selectedLog,
    selectedSampleIndex,
    selectedWorkspaceTab,
    selectedSample,
    sampleStatus,
    sampleError,
    selectedSampleTab,
    showingSampleDialog,
    status,
    capabilities,
    offcanvas,
    showFind,
    filter,
    epoch,
    sort,
    scores,
    score,
    filteredSamples,
    groupBy,
    groupByOrder,
  ]);

  const handleSampleShowingDialog = useCallback(
    (show) => {
      setShowingSampleDialog(show);
      if (!show) {
        setSelectedSample(undefined);
        setSelectedSampleTab(undefined);
      }
    },
    [
      setShowingSampleDialog,
      setSelectedSample,
      setSelectedSampleTab,
      selectedSample,
    ],
  );

  useEffect(() => {
    const samples = selectedLog?.contents?.sampleSummaries || [];
    const filtered = samples.filter((sample) => {
      // Filter by epoch if specified
      if (epoch && epoch !== "all") {
        if (epoch !== sample.epoch + "") {
          return false;
        }
      }

      // Apply the filter
      const filterFn = filterFnForType(filter);
      if (filterFn && filter.value) {
        return filterFn(samplesDescriptor, sample, filter.value);
      } else {
        return true;
      }
    });

    // Sort the samples
    const { sorted, order } = sortSamples(sort, filtered, samplesDescriptor);

    // Set the grouping
    let grouping = "none";
    if (samplesDescriptor?.epochs > 1) {
      if (byEpoch(sort) || epoch !== "all") {
        grouping = "epoch";
      } else if (bySample(sort)) {
        grouping = "sample";
      }
    }

    setFilteredSamples(sorted);
    setGroupBy(grouping);
    setGroupByOrder(order);
  }, [selectedLog, filter, sort, epoch]);

  const samplesDescriptor = createsSamplesDescriptor(
    scores,
    selectedLog.contents?.sampleSummaries,
    selectedLog.contents?.eval?.config?.epochs || 1,
    context,
    score,
  );

  const refreshSampleTab = useCallback(
    (sample) => {
      if (selectedSampleTab === undefined) {
        const defaultTab =
          sample.events && sample.events.length > 0
            ? kSampleTranscriptTabId
            : kSampleMessagesTabId;
        setSelectedSampleTab(defaultTab);
      }
    },
    [selectedSampleTab, showingSampleDialog],
  );

  // The main application reference
  const mainAppRef = useRef();

  // Loads a sample
  useEffect(() => {
    // Clear the selected sample
    if (!selectedLog || selectedSampleIndex === -1) {
      setSelectedSample(undefined);
      return;
    }

    // If already loading the selected sample, do nothing
    if (loadingSampleIndexRef.current === selectedSampleIndex) {
      return;
    }

    if (
      !showingSampleDialog &&
      selectedLog.contents.sampleSummaries.length > 1
    ) {
      return;
    }

    if (selectedSampleIndex < filteredSamples.length) {
      const summary = filteredSamples[selectedSampleIndex];
      // If this sample is already loaded, don't bother
      if (
        selectedSample &&
        selectedSample.id === summary.id &&
        selectedSample.epoch === summary.epoch
      ) {
        return;
      }

      // Load the selected sample (if not already loaded)
      loadingSampleIndexRef.current = selectedSampleIndex;
      setSampleStatus("loading");
      setSampleError(undefined);

      api
        .get_log_sample(selectedLog.name, summary.id, summary.epoch)
        .then((sample) => {
          // migrate transcript to new structure
          // @ts-ignore
          if (sample.transcript) {
            // @ts-ignore
            sample.events = sample.transcript.events;
            // @ts-ignore
            sample.attachments = sample.transcript.content;
          }
          sample.attachments = sample.attachments || {};
          sample.input = resolveAttachments(sample.input, sample.attachments);
          sample.messages = resolveAttachments(
            sample.messages,
            sample.attachments,
          );
          sample.events = resolveAttachments(sample.events, sample.attachments);
          sample.attachments = {};

          setSelectedSample(sample);

          refreshSampleTab(sample);

          setSampleStatus("ok");
          loadingSampleIndexRef.current = null;
        })
        .catch((e) => {
          setSampleStatus("error");
          setSampleError(e);
          setSelectedSample(undefined);
          loadingSampleIndexRef.current = null;
        });
    }
  }, [
    selectedSample,
    selectedSampleIndex,
    showingSampleDialog,
    selectedLog,
    filteredSamples,
    setSelectedSample,
    setSampleStatus,
    setSampleError,
  ]);

  // Read header information for the logs
  // and then update
  useEffect(() => {
    const loadHeaders = async () => {
      setHeadersLoading(true);

      // Group into chunks
      const chunkSize = 8;
      const fileLists = [];
      for (let i = 0; i < logs.files.length; i += chunkSize) {
        let chunk = logs.files.slice(i, i + chunkSize).map((log) => log.name);
        fileLists.push(chunk);
      }

      // Chunk by chunk, read the header information
      try {
        for (const fileList of fileLists) {
          const headers = await api.get_log_headers(fileList);
          setLogHeaders((prev) => {
            const updatedHeaders = {};
            headers.forEach((header, index) => {
              const logFile = fileList[index];
              updatedHeaders[logFile] = header;
            });
            return { ...prev, ...updatedHeaders };
          });

          if (headers.length === chunkSize) {
            await sleep(5000); // Pause between chunks
          }
        }
      } catch (e) {
        console.log(e);
        setStatus({ loading: false, error: e });
      }

      setHeadersLoading(false);
    };

    loadHeaders();
  }, [logs, setStatus, setLogHeaders, setHeadersLoading]);

  /**
   * Resets the workspace tab based on the provided log's state.
   *
   * Determines whether the workspace tab should display samples or info,
   * depending on the presence of samples and the log status.
   *
   * @param {import("./api/Types.mjs").EvalSummary} log - The log object containing sample summaries and status.
   * @returns {void}
   */
  const resetWorkspace = useCallback(
    /**
     * @param {import("./api/Types.mjs").EvalSummary} log
     */
    (log) => {
      // Reset the workspace tab
      const hasSamples =
        !!log.sampleSummaries && log.sampleSummaries.length > 0;
      const showSamples = log.status !== "error" && hasSamples;
      setSelectedWorkspaceTab(
        showSamples ? kEvalWorkspaceTabId : kInfoWorkspaceTabId,
      );

      // Select the default scorer to use
      const scorer = log.results?.scores[0]
        ? {
            name: log.results?.scores[0].name,
            scorer: log.results?.scores[0].scorer,
          }
        : undefined;
      const scorers = (log.results?.scores || [])
        .map((score) => {
          return {
            name: score.name,
            scorer: score.scorer,
          };
        })
        .reduce((accum, scorer) => {
          if (
            !accum.find((sc) => {
              return scorer.scorer === sc.scorer && scorer.name === sc.name;
            })
          ) {
            accum.push(scorer);
          }
          return accum;
        }, []);

      // Reset state
      setScores(scorers);
      setScore(scorer);

      setEpoch("all");
      setFilter({});
      setSort(kDefaultSort);

      // Reset the sample tab
      setSelectedSampleTab(undefined);
      setSelectedSample(undefined);
      if (showSamples) {
        setSelectedSampleIndex(0);
      } else {
        setSelectedSampleIndex(-1);
      }
    },
    [setSelectedWorkspaceTab],
  );

  // Load a specific log
  useEffect(() => {
    const loadSpecificLog = async () => {
      const targetLog = logs.files[selectedLogIndex];
      if (targetLog && (!selectedLog || selectedLog.name !== targetLog.name)) {
        try {
          setStatus({ loading: true, error: undefined });
          const logContents = await loadLog(targetLog.name);
          if (logContents) {
            const log = logContents;
            setSelectedLog({
              contents: log,
              name: targetLog.name,
            });

            // Reset the workspace tab
            resetWorkspace(log);

            setStatus({ loading: false, error: undefined });
          }
        } catch (e) {
          console.log(e);
          setStatus({ loading: false, error: e });
        }
      } else if (logs.log_dir && logs.files.length === 0) {
        setStatus({
          loading: false,
          error: new Error(
            `No log files to display in the directory ${logs.log_dir}. Are you sure this is the correct log directory?`,
          ),
        });
      }
    };

    loadSpecificLog();
  }, [
    selectedLogIndex,
    logs,
    capabilities,
    selectedLog,
    setSelectedLog,
    setStatus,
  ]);

  // Load the list of logs
  const loadLogs = async () => {
    try {
      const result = await api.get_log_paths();
      return result;
    } catch (e) {
      // Show an error
      console.log(e);
      setStatus({ loading: false, error: e });
    }
  };

  // Load a specific log file
  const loadLog = async (logFileName) => {
    try {
      const logContents = await api.get_log_summary(logFileName);
      return logContents;
    } catch (e) {
      // Show an error
      console.log(e);
      setStatus({ loading: false, error: e });
    }
  };

  const refreshLog = useCallback(async () => {
    try {
      setStatus({ loading: true, error: undefined });
      const targetLog = logs.files[selectedLogIndex];
      const logContents = await loadLog(targetLog.name);
      if (logContents) {
        const log = logContents;
        if (log.status !== "started") {
          setLogHeaders((prev) => {
            const updatedState = { ...prev };
            const freshHeaders = {
              eval: log.eval,
              plan: log.plan,
              results: log.results,
              stats: log.stats,
              status: log.status,
              version: log.version,
            };
            updatedState[targetLog.name] = freshHeaders;
            return updatedState;
          });
        }

        setSelectedLog({
          contents: log,
          name: targetLog.name,
        });

        // Reset the workspace tab
        resetWorkspace(log);

        setStatus({ loading: false, error: undefined });
      }
    } catch (e) {
      // Show an error
      console.log(e);
      setStatus({ loading: false, error: e });
    }
  }, [logs, selectedLogIndex, setStatus, setSelectedLog, setLogHeaders]);

  const showLogFile = useCallback(
    async (logUrl) => {
      const index = logs.files.findIndex((val) => {
        return logUrl.endsWith(val.name);
      });
      if (index > -1) {
        setSelectedLogIndex(index);
      } else {
        const result = await loadLogs();
        const idx = result.files.findIndex((file) => {
          return logUrl.endsWith(file.name);
        });
        setLogs(result);
        setSelectedLogIndex(idx > -1 ? idx : 0);
      }
    },
    [logs, setSelectedLogIndex, setLogs],
  );

  const refreshLogList = useCallback(async () => {
    const currentLog = logs.files[selectedLogIndex > -1 ? selectedLogIndex : 0];

    const refreshedLogs = await loadLogs();
    const newIndex = refreshedLogs.files.findIndex((file) => {
      return currentLog.name.endsWith(file.name);
    });
    setLogs(refreshedLogs);
    setSelectedLogIndex(newIndex);
  }, [logs, selectedLogIndex, setSelectedLogIndex, setLogs]);

  const onMessage = useMemo(() => {
    return async (e) => {
      const type = e.data.type || e.data.message;
      switch (type) {
        case "updateState": {
          if (e.data.url) {
            const decodedUrl = decodeURIComponent(e.data.url);
            showLogFile(decodedUrl);
          }
          break;
        }
        case "backgroundUpdate": {
          const decodedUrl = decodeURIComponent(e.data.url);
          const log_dir = e.data.log_dir;
          const isFocused = document.hasFocus();
          if (!isFocused) {
            if (log_dir === logs.log_dir) {
              showLogFile(decodedUrl);
            } else {
              api.open_log_file(e.data.url, e.data.log_dir);
            }
          } else {
            refreshLogList();
          }
          break;
        }
      }
    };
  }, [logs, showLogFile, refreshLogList]);

  // listen for updateState messages from vscode
  useEffect(() => {
    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
    };
  }, [onMessage]);

  useEffect(() => {
    const loadLogsAndState = async () => {
      // See whether a specific task_file has been passed.
      const urlParams = new URLSearchParams(window.location.search);

      // Determine the capabilities
      const extensionVersionEl = document.querySelector(
        'meta[name="inspect-extension:version"]',
      );
      const extensionVersion = extensionVersionEl
        ? extensionVersionEl.getAttribute("content")
        : undefined;

      if (isVscode()) {
        if (!extensionVersion) {
          setCapabilities({ downloadFiles: false, webWorkers: false });
        }
      }

      setOffcanvas(true);

      // If the URL provides a task file, load that
      const logPath = urlParams.get("task_file");

      // Replace spaces with a '+' sign:
      const resolvedLogPath = logPath ? logPath.replace(" ", "+") : logPath;
      const load = resolvedLogPath
        ? async () => {
            return {
              log_dir: "",
              files: [{ name: resolvedLogPath }],
            };
          }
        : loadLogs;

      const embeddedState = document.getElementById("logview-state");
      if (embeddedState) {
        const state = JSON.parse(embeddedState.textContent);
        onMessage({ data: state });
      } else {
        const result = await load();
        setLogs(result);

        // If a log file was passed, select it
        const log_file = urlParams.get("log_file");
        if (log_file) {
          const index = result.files.findIndex((val) => {
            return log_file.endsWith(val.name);
          });
          if (index > -1) {
            setSelectedLogIndex(index);
          }
        } else if (selectedLogIndex === -1) {
          setSelectedLogIndex(0);
        }
      }

      new ClipboardJS(".clipboard-button,.copy-button");

      if (pollForLogs) {
        setInterval(() => {
          api.client_events().then(async (events) => {
            if (events.includes("reload")) {
              window.location.reload();
            }
            if (events.includes("refresh-evals")) {
              const logs = await load();
              setLogs(logs);
              setSelectedLogIndex(0);
            }
          });
        }, 1000);
      }
    };

    loadLogsAndState();
  }, []);

  // Configure an app envelope specific to the current state
  // if there are no log files, then don't show sidebar
  const fullScreen = logs.files.length === 1 && !logs.log_dir;
  const sidebar =
    !fullScreen && selectedLog.contents
      ? html`
          <${Sidebar}
            logs=${logs}
            logHeaders=${logHeaders}
            loading=${headersLoading}
            offcanvas=${offcanvas}
            selectedIndex=${selectedLogIndex}
            onSelectedIndexChanged=${(index) => {
              setSelectedLogIndex(index);

              // hide the sidebar offcanvas
              var myOffcanvas = document.getElementById("sidebarOffCanvas");
              var bsOffcanvas = Offcanvas.getInstance(myOffcanvas);
              if (bsOffcanvas) {
                bsOffcanvas.hide();
              }
            }}
          />
        `
      : "";

  const fullScreenClz = fullScreen ? " full-screen" : "";
  const offcanvasClz = offcanvas ? " off-canvas" : "";

  const hideFind = useCallback(() => {
    clearDocumentSelection();
    if (showFind) {
      setShowFind(false);
    }
  }, [showFind, setShowFind]);

  const showToggle = logs.files.length > 1 || logs.log_dir;

  /**
   * Determines the sample mode based on the selected log's contents.
   *
   * @type {import("./Types.mjs").SampleMode}
   */
  const sampleMode =
    selectedLog?.contents?.sampleSummaries === undefined ||
    selectedLog.contents.sampleSummaries.length === 0
      ? "none"
      : selectedLog.contents.sampleSummaries.length === 1
        ? "single"
        : "many";
  return html`
    <${AppErrorBoundary}>
    ${sidebar}
    <div ref=${mainAppRef} class="app-main-grid${fullScreenClz}${offcanvasClz}" tabIndex="0" onKeyDown=${(
      e,
    ) => {
      // regular browsers user their own find
      if (!getVscodeApi()) {
        return;
      }

      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        setShowFind(true);
      } else if (e.key === "Escape") {
        hideFind();
      }
    }}>
      ${showFind ? html`<${FindBand} hideBand=${hideFind} />` : ""}
      <${ProgressBar} animating=${status.loading}  containerStyle=${{
        background: "var(--bs-light)",
        marginBottom: "-1px",
      }}/>
      ${
        status.error
          ? html`<${ErrorPanel}
              title="An error occurred while loading this task."
              error=${status.error}
            />`
          : html`<${WorkSpace}
              task_id=${selectedLog?.contents?.eval?.task_id}
              logFileName=${selectedLog?.name}
              evalStatus=${selectedLog?.contents?.status}
              evalError=${selectedLog?.contents?.error}
              evalVersion=${selectedLog?.contents?.version}
              evalSpec=${selectedLog?.contents?.eval}
              evalPlan=${selectedLog?.contents?.plan}
              evalStats=${selectedLog?.contents?.stats}
              evalResults=${selectedLog?.contents?.results}
              showToggle=${showToggle}
              samples=${filteredSamples}
              sampleMode=${sampleMode}
              groupBy=${groupBy}
              groupByOrder=${groupByOrder}
              sampleStatus=${sampleStatus}
              sampleError=${sampleError}
              samplesDescriptor=${samplesDescriptor}
              refreshLog=${refreshLog}
              offcanvas=${offcanvas}
              capabilities=${capabilities}
              selected=${selectedLogIndex}
              selectedSample=${selectedSample}
              selectedSampleIndex=${selectedSampleIndex}
              setSelectedSampleIndex=${setSelectedSampleIndex}
              showingSampleDialog=${showingSampleDialog}
              setShowingSampleDialog=${handleSampleShowingDialog}
              selectedTab=${selectedWorkspaceTab}
              setSelectedTab=${setSelectedWorkspaceTab}
              selectedSampleTab=${selectedSampleTab}
              setSelectedSampleTab=${setSelectedSampleTab}
              sort=${sort}
              setSort=${setSort}
              epochs=${selectedLog?.contents?.eval?.config?.epochs}
              epoch=${epoch}
              setEpoch=${setEpoch}
              filter=${filter}
              setFilter=${setFilter}
              score=${score}
              setScore=${setScore}
              scores=${scores}
              renderContext=${context}
            />`
      }
    </div>
    ${afterBodyElements}
    </${AppErrorBoundary}>
  `;
}
