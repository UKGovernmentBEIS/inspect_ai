import "bootstrap-icons/font/bootstrap-icons.css";
import "bootstrap/dist/css/bootstrap.css";

import "prismjs";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-clike";
import "prismjs/components/prism-javascript";
import "prismjs/components/prism-json";
import "prismjs/components/prism-python";
import "prismjs/themes/prism.css";

import "../App.css";

import { AppErrorBoundary } from "./AppErrorBoundary";
import { ErrorPanel } from "./components/ErrorPanel";
import { ProgressBar } from "./components/ProgressBar";
import { clearDocumentSelection } from "./utils/browser";
import { debounce, sleep } from "./utils/sync";

import { FindBand } from "./components/FindBand";
import { kDefaultSort } from "./constants";
import {
  createEvalDescriptor,
  createSamplesDescriptor,
} from "./samples/descriptor/samplesDescriptor";
import { filterSamples } from "./samples/sample-tools/filters";
import {
  byEpoch,
  bySample,
  sortSamples,
} from "./samples/sample-tools/SortFilter";
import { resolveAttachments } from "./utils/attachments";
import { getVscodeApi } from "./utils/vscode";
import { Sidebar } from "./workspace/sidebar/Sidebar.tsx";
import { WorkSpace } from "./workspace/WorkSpace";

import ClipboardJS from "clipboard";
import clsx from "clsx";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ClientAPI,
  EvalLogHeader,
  EvalSummary,
  HostMessage,
  LogFiles,
  SampleSummary,
} from "./api/types.ts";
import {
  kEvalWorkspaceTabId,
  kInfoWorkspaceTabId,
  kSampleMessagesTabId,
  kSampleTranscriptTabId,
} from "./constants";
import {
  ApplicationState,
  AppStatus,
  Capabilities,
  CurrentLog,
  ScoreFilter,
  ScoreLabel,
} from "./types.ts";
import { EvalSample } from "./types/log";

interface AppProps {
  api: ClientAPI;
  applicationState?: ApplicationState;
  saveApplicationState?: (state: ApplicationState) => void;
  pollForLogs: boolean;
  capabilities: Capabilities;
}

/**
 * Renders the Main Application
 */
export const App: React.FC<AppProps> = ({
  api,
  applicationState,
  saveApplicationState,
  pollForLogs = true,
  capabilities,
}) => {
  // List of Logs
  const [logs, setLogs] = useState<LogFiles>(
    applicationState?.logs || { log_dir: "", files: [] },
  );
  const [selectedLogIndex, setSelectedLogIndex] = useState<number>(
    applicationState?.selectedLogIndex !== undefined
      ? applicationState.selectedLogIndex
      : -1,
  );

  // Log Headers
  const [logHeaders, setLogHeaders] = useState<Record<string, EvalLogHeader>>(
    applicationState?.logHeaders || {},
  );
  const [headersLoading, setHeadersLoading] = useState<boolean>(
    applicationState?.headersLoading || false,
  );

  const [selectedLog, setSelectedLog] = useState<CurrentLog | undefined>(
    applicationState?.selectedLog,
  );

  // Workspace (the selected tab)
  const [selectedWorkspaceTab, setSelectedWorkspaceTab] = useState<string>(
    applicationState?.selectedWorkspaceTab || kEvalWorkspaceTabId,
  );
  const [selectedSampleIndex, setSelectedSampleIndex] = useState<number>(
    applicationState?.selectedSampleIndex !== undefined
      ? applicationState.selectedSampleIndex
      : -1,
  );
  const [selectedSample, setSelectedSample] = useState<EvalSample | undefined>(
    applicationState?.selectedSample,
  );
  const [sampleStatus, setSampleStatus] = useState<"loading" | "ok" | "error">(
    applicationState?.sampleStatus || "loading",
  );
  const [sampleError, setSampleError] = useState<Error | undefined>(
    applicationState?.sampleError,
  );
  const [selectedSampleTab, setSelectedSampleTab] = useState<
    string | undefined
  >(applicationState?.selectedSampleTab);
  const sampleScrollPosition = useRef<number>(
    applicationState?.sampleScrollPosition || 0,
  );
  const loadingSampleIndexRef = useRef<number | null>(null);
  const workspaceTabScrollPosition = useRef<Record<string, number>>(
    applicationState?.workspaceTabScrollPosition || {},
  );

  const [showingSampleDialog, setShowingSampleDialog] = useState<boolean>(
    !!applicationState?.showingSampleDialog,
  );

  // App loading status
  const [status, setStatus] = useState<AppStatus>(
    applicationState?.status || { loading: false },
  );

  // Other application state
  const [offcanvas, setOffcanvas] = useState<boolean>(
    applicationState?.offcanvas || false,
  );
  const [showFind, setShowFind] = useState<boolean>(
    applicationState?.showFind || false,
  );

  // Filtering and sorting
  const [filter, setFilter] = useState<ScoreFilter>(
    applicationState?.filter || {},
  );

  const [epoch, setEpoch] = useState<string>(applicationState?.epoch || "all");
  const [sort, setSort] = useState<string>(
    applicationState?.sort || kDefaultSort,
  );

  const [scores, setScores] = useState<ScoreLabel[]>(
    applicationState?.scores || [],
  );

  const [score, setScore] = useState<ScoreLabel | undefined>(
    applicationState?.score,
  );

  // Re-filter the samples
  const [filteredSamples, setFilteredSamples] = useState<SampleSummary[]>(
    applicationState?.filteredSamples || [],
  );
  const [groupBy, setGroupBy] = useState<"none" | "epoch" | "sample">(
    applicationState?.groupBy || "none",
  );
  const [groupByOrder, setGroupByOrder] = useState<"asc" | "desc">(
    applicationState?.groupByOrder || "asc",
  );

  const saveState = useCallback(() => {
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
      sampleScrollPosition: sampleScrollPosition.current,
      workspaceTabScrollPosition: workspaceTabScrollPosition.current,
    };
    if (saveApplicationState) {
      saveApplicationState(state);
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

  const saveStateRef = useRef(saveState);
  // Update the ref whenever saveState changes
  useEffect(() => {
    saveStateRef.current = saveState;
  }, [saveState]);

  const setSampleScrollPosition = useCallback(
    debounce((position) => {
      sampleScrollPosition.current = position;
      saveStateRef.current();
    }, 1000),
    [],
  );

  const setWorkspaceTabScrollPosition = useCallback(
    debounce((tab, position) => {
      if (workspaceTabScrollPosition.current[tab] !== position) {
        workspaceTabScrollPosition.current = {
          ...workspaceTabScrollPosition.current,
          [tab]: position,
        };
        saveStateRef.current();
      }
    }, 1000),
    [],
  );

  // Save state when it changes, so that we can restore it later
  //
  useEffect(() => {
    saveStateRef.current();
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
    (show: boolean) => {
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
    const { result: prefiltered } =
      evalDescriptor && filter?.value
        ? filterSamples(evalDescriptor, samples, filter.value)
        : { result: samples };

    const filtered = prefiltered.filter((sample) => {
      // Filter by epoch if specified
      if (epoch && epoch !== "all") {
        if (epoch !== String(sample.epoch)) {
          return false;
        }
      }
      return true;
    });

    // Sort the samples
    if (samplesDescriptor) {
      const { sorted, order } = sortSamples(sort, filtered, samplesDescriptor);
      setFilteredSamples(sorted);
      setGroupByOrder(order);
    }

    // Set the grouping
    let grouping: "none" | "epoch" | "sample" = "none";
    if (
      samplesDescriptor?.evalDescriptor?.epochs &&
      samplesDescriptor.evalDescriptor.epochs > 1
    ) {
      if (byEpoch(sort) || epoch !== "all") {
        grouping = "epoch";
      } else if (bySample(sort)) {
        grouping = "sample";
      }
    }
    setGroupBy(grouping);
  }, [selectedLog, filter, sort, epoch]);

  const evalDescriptor = useMemo(() => {
    return createEvalDescriptor(
      scores,
      selectedLog?.contents?.eval?.config?.epochs || 1,
      selectedLog?.contents?.sampleSummaries,
    );
  }, [selectedLog, scores]);

  const samplesDescriptor = useMemo(() => {
    return evalDescriptor && score
      ? createSamplesDescriptor(evalDescriptor, score)
      : undefined;
  }, [evalDescriptor, score]);

  useEffect(() => {
    if (selectedSampleTab === undefined && selectedSample) {
      setSelectedSampleTab(
        selectedSample.events && selectedSample.events.length > 0
          ? kSampleTranscriptTabId
          : kSampleMessagesTabId,
      );
    }
  }, [selectedSample, selectedSampleTab]);

  // The main application reference
  const mainAppRef = useRef<HTMLDivElement>(null);

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
          if (sample) {
            // This migrates old samples (with raw transcript element)
            // to the new structure (hence the type bypass).
            const anySample = sample as any;
            if (anySample.transcript) {
              sample.events = anySample.transcript.events;
              sample.attachments = anySample.transcript.content;
            }
            sample.attachments = sample.attachments || {};
            sample.input = resolveAttachments(sample.input, sample.attachments);
            sample.messages = resolveAttachments(
              sample.messages,
              sample.attachments,
            );
            sample.events = resolveAttachments(
              sample.events,
              sample.attachments,
            );
            sample.attachments = {};

            sampleScrollPosition.current = 0;
            setSelectedSample(sample);

            setSampleStatus("ok");
            loadingSampleIndexRef.current = null;
          } else {
            throw Error("Unable to load sample - an unknown error occurred.");
          }
        })
        .catch((e) => {
          setSampleStatus("error");
          setSampleError(e);

          sampleScrollPosition.current = 0;
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
            const updatedHeaders: Record<string, EvalLogHeader> = {};
            headers.forEach((header, index) => {
              const logFile = fileList[index];
              updatedHeaders[logFile] = header as EvalLogHeader;
            });
            return { ...prev, ...updatedHeaders };
          });

          if (headers.length === chunkSize) {
            await sleep(5000); // Pause between chunks
          }
        }
      } catch (e: unknown) {
        if (
          e instanceof Error &&
          (e.message === "Load failed" || e.message === "Failed to fetch")
        ) {
          // This will happen if the server disappears (e.g. inspect view is terminated)
          setStatus({ loading: false });
        } else {
          console.log(e);
          setStatus({ loading: false, error: e as Error });
        }
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
   */
  const resetWorkspace = useCallback(
    (log: EvalSummary) => {
      // Reset the workspace tab
      const hasSamples =
        !!log.sampleSummaries && log.sampleSummaries.length > 0;
      const showSamples = hasSamples;
      setSelectedWorkspaceTab(
        log.status !== "error" && hasSamples
          ? kEvalWorkspaceTabId
          : kInfoWorkspaceTabId,
      );

      // Select the default scorer to use
      const scorer = defaultScorer(log);
      const scorers = defaultScorers(log);

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

      workspaceTabScrollPosition.current = {};
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
          setStatus({ loading: false, error: e as Error });
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
  }, [selectedLogIndex, logs, selectedLog, setSelectedLog, setStatus]);

  // Load the list of logs
  const loadLogs = async (): Promise<LogFiles> => {
    try {
      const result = await api.get_log_paths();

      return result;
    } catch (e) {
      // Show an error
      console.log(e);
      setStatus({ loading: false, error: e as Error });
      return { log_dir: "", files: [] };
    }
  };

  // Load a specific log file
  const loadLog = async (logFileName: string) => {
    try {
      const logContents = await api.get_log_summary(logFileName);
      return logContents;
    } catch (e) {
      // Show an error
      console.log(e);
      setStatus({ loading: false, error: e as Error });
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
            const freshHeaders: EvalLogHeader = {
              eval: log.eval,
              plan: log.plan,
              results: log.results !== null ? log.results : undefined,
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
      setStatus({ loading: false, error: e as Error });
    }
  }, [logs, selectedLogIndex, setStatus, setSelectedLog, setLogHeaders]);

  const showLogFile = useCallback(
    async (logUrl: string) => {
      const index = logs.files.findIndex((val) => {
        return logUrl.endsWith(val.name);
      });
      if (index > -1) {
        setSelectedLogIndex(index);
      } else {
        const result = await loadLogs();
        const idx = result?.files.findIndex((file) => {
          return logUrl.endsWith(file.name);
        });
        setLogs(result || { log_dir: "", files: [] });
        setSelectedLogIndex(idx && idx > -1 ? idx : 0);
      }
    },
    [logs, setSelectedLogIndex, setLogs],
  );

  const refreshLogList = useCallback(async () => {
    const currentLog = logs.files[selectedLogIndex > -1 ? selectedLogIndex : 0];
    const refreshedLogs = await loadLogs();
    setLogs(refreshedLogs || { log_dir: "", files: [] });

    const newIndex = refreshedLogs?.files.findIndex((file) => {
      return currentLog.name.endsWith(file.name);
    });
    if (newIndex !== undefined) {
      setSelectedLogIndex(newIndex);
    }
  }, [logs, selectedLogIndex, setSelectedLogIndex, setLogs]);

  const onMessage = useCallback(
    async (e: HostMessage) => {
      switch (e.data.type) {
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
    },
    [logs, showLogFile, refreshLogList],
  );

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

      // If the URL provides a task file, load that
      const logPath = urlParams.get("task_file");

      // Replace spaces with a '+' sign:
      const resolvedLogPath = logPath ? logPath.replace(" ", "+") : logPath;
      const load = resolvedLogPath
        ? async (): Promise<LogFiles> => {
            return {
              log_dir: "",
              files: [{ name: resolvedLogPath }],
            };
          }
        : loadLogs;

      const embeddedState = document.getElementById("logview-state");
      if (embeddedState) {
        const state = JSON.parse(embeddedState.textContent || "");
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
        let retryDelay = 1000;
        const maxRetryDelay = 60000;

        const pollEvents = async () => {
          try {
            const events = await api.client_events();

            if (events.includes("reload")) {
              window.location.reload();
            }

            if (events.includes("refresh-evals")) {
              const logs = await load();
              setLogs(logs);
              setSelectedLogIndex(0);
            }

            // Reset delay after a successful call
            retryDelay = 1000;
          } catch (error) {
            console.error("Error fetching client events:", error);

            // Exponential backoff with capping
            retryDelay = Math.min(retryDelay * 2, maxRetryDelay);
          } finally {
            // Schedule the next poll
            setTimeout(pollEvents, retryDelay);
          }
        };

        // Start polling
        pollEvents();
      }
    };

    loadLogsAndState();
  }, []);

  // Configure an app envelope specific to the current state
  // if there are no log files, then don't show sidebar
  const fullScreen = logs.files.length === 1 && !logs.log_dir;

  const hideFind = useCallback(() => {
    clearDocumentSelection();
    if (showFind) {
      setShowFind(false);
    }
  }, [showFind, setShowFind]);

  const showToggle = logs.files.length > 1 || !!logs.log_dir || false;

  /**
   * Determines the sample mode based on the selected log's contents.
   */
  const sampleMode =
    selectedLog?.contents?.sampleSummaries === undefined ||
    selectedLog.contents.sampleSummaries.length === 0
      ? "none"
      : selectedLog.contents.sampleSummaries.length === 1
        ? "single"
        : "many";
  return (
    <AppErrorBoundary>
      {!fullScreen && selectedLog?.contents ? (
        <Sidebar
          logs={logs}
          logHeaders={logHeaders}
          loading={headersLoading}
          offcanvas={offcanvas}
          setOffcanvas={setOffcanvas}
          selectedIndex={selectedLogIndex}
          onSelectedIndexChanged={(index) => {
            setSelectedLogIndex(index);
            setOffcanvas(false);
          }}
        />
      ) : undefined}
      <div
        ref={mainAppRef}
        className={clsx(
          "app-main-grid",
          fullScreen ? "full-screen" : undefined,
          offcanvas ? "off-canvas" : undefined,
        )}
        tabIndex={0}
        onKeyDown={(e) => {
          // regular browsers user their own find
          if (!getVscodeApi()) {
            return;
          }

          if ((e.ctrlKey || e.metaKey) && e.key === "f") {
            setShowFind(true);
          } else if (e.key === "Escape") {
            hideFind();
          }
        }}
      >
        {showFind ? <FindBand hideBand={hideFind} /> : ""}
        <ProgressBar animating={status?.loading} />
        {status?.error ? (
          <ErrorPanel
            title="An error occurred while loading this task."
            error={status.error}
          />
        ) : (
          <WorkSpace
            task_id={selectedLog?.contents?.eval?.task_id}
            logFileName={selectedLog?.name}
            evalStatus={selectedLog?.contents?.status}
            evalError={filterNull(selectedLog?.contents?.error)}
            evalVersion={selectedLog?.contents?.version}
            evalSpec={selectedLog?.contents?.eval}
            evalPlan={selectedLog?.contents?.plan}
            evalStats={selectedLog?.contents?.stats}
            evalResults={filterNull(selectedLog?.contents?.results)}
            showToggle={showToggle}
            samples={filteredSamples}
            sampleMode={sampleMode}
            groupBy={groupBy}
            groupByOrder={groupByOrder}
            sampleStatus={sampleStatus}
            sampleError={sampleError}
            samplesDescriptor={samplesDescriptor}
            refreshLog={refreshLog}
            offcanvas={offcanvas}
            setOffcanvas={setOffcanvas}
            capabilities={capabilities}
            selectedSample={selectedSample}
            selectedSampleIndex={selectedSampleIndex}
            setSelectedSampleIndex={setSelectedSampleIndex}
            showingSampleDialog={showingSampleDialog}
            setShowingSampleDialog={handleSampleShowingDialog}
            selectedTab={selectedWorkspaceTab}
            setSelectedTab={setSelectedWorkspaceTab}
            selectedSampleTab={selectedSampleTab}
            setSelectedSampleTab={setSelectedSampleTab}
            sort={sort}
            setSort={setSort}
            epochs={selectedLog?.contents?.eval?.config?.epochs}
            epoch={epoch}
            setEpoch={setEpoch}
            filter={filter}
            setFilter={setFilter}
            score={score}
            setScore={setScore}
            scores={scores}
            sampleScrollPositionRef={sampleScrollPosition}
            setSampleScrollPosition={setSampleScrollPosition}
            workspaceTabScrollPositionRef={workspaceTabScrollPosition}
            setWorkspaceTabScrollPosition={setWorkspaceTabScrollPosition}
          />
        )}
      </div>
    </AppErrorBoundary>
  );
};

const filterNull = <T,>(obj: T | null): T | undefined => {
  if (obj === null) {
    return undefined;
  }
  return obj;
};

interface ScorerInfo {
  name: string;
  scorer: string;
}

/**
 * Determines the default scorer for a log
 */
const defaultScorer = (log: EvalSummary): ScorerInfo | undefined => {
  if (log.sampleSummaries.length === 0) {
    return undefined;
  }

  // Select the default scorer to use
  const scores = log.sampleSummaries[0].scores;

  const scorer = log.results?.scores[0]
    ? {
        name: log.results?.scores[0].name,
        scorer: log.results?.scores[0].scorer,
      }
    : log.sampleSummaries.length > 0 && scores !== null
      ? {
          name: Object.keys(scores)[0],
          scorer: Object.keys(scores)[0],
        }
      : undefined;
  return scorer;
};

/**
 * Determines the default scorers for a log
 */
const defaultScorers = (log: EvalSummary): Array<ScorerInfo> => {
  if (log.results?.scores) {
    return (log.results?.scores || [])
      .map((score): ScorerInfo => {
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
      }, [] as Array<ScorerInfo>);
  } else if (log.sampleSummaries && log.sampleSummaries.length > 0) {
    const scores = log.sampleSummaries[0].scores;

    if (scores !== null) {
      return Object.keys(scores).map((key) => {
        return {
          name: key,
          scorer: key,
        };
      });
    } else {
      return [];
    }
  } else {
    return [];
  }
};
