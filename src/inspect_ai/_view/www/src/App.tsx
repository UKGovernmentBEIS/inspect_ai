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

import { ErrorPanel } from "./components/ErrorPanel";
import { ProgressBar } from "./components/ProgressBar";
import { debounce, sleep } from "./utils/sync";

import { FindBand } from "./components/FindBand";
import {
  kDefaultSort,
  kEpochAscVal,
  kSampleAscVal,
  kScoreAscVal,
} from "./constants";
import { filterSamples } from "./samples/sample-tools/filters";
import {
  byEpoch,
  bySample,
  sortSamples,
} from "./samples/sample-tools/SortFilter";
import { getVscodeApi } from "./utils/vscode";
import { Sidebar } from "./workspace/sidebar/Sidebar.tsx";
import { WorkSpace } from "./workspace/WorkSpace";

import ClipboardJS from "clipboard";
import clsx from "clsx";
import { FC, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ClientAPI,
  EvalLogHeader,
  EvalSummary,
  HostMessage,
  LogFiles,
  PendingSamples,
  SampleSummary,
} from "./api/types.ts";
import { useAppContext } from "./AppContext.tsx";
import {
  kEvalWorkspaceTabId,
  kInfoWorkspaceTabId,
  kSampleMessagesTabId,
  kSampleTranscriptTabId,
} from "./constants";
import { useLogsContext } from "./LogsContext.tsx";
import {
  createEvalDescriptor,
  createSamplesDescriptor,
} from "./samples/descriptor/samplesDescriptor.tsx";
import { sampleDataAdapter } from "./samples/sampleDataAdapter.ts";
import { getAvailableScorers, getDefaultScorer } from "./scoring/utils.ts";
import {
  ApplicationState,
  RunningSampleData,
  ScoreFilter,
  ScoreLabel,
} from "./types.ts";
import { EvalSample, Timeout } from "./types/log";
import { resolveAttachments } from "./utils/attachments.ts";

interface AppProps {
  api: ClientAPI;
  applicationState?: ApplicationState;
  saveApplicationState?: (state: ApplicationState) => void;
}

/**
 * Renders the Main Application
 */
export const App: FC<AppProps> = ({
  api,
  applicationState,
  saveApplicationState,
}) => {
  // Application Context
  const appContext = useAppContext();
  const logsContext = useLogsContext();

  // The main application reference
  const mainAppRef = useRef<HTMLDivElement>(null);

  const [logHeaders, setLogHeaders] = useState<Record<string, EvalLogHeader>>(
    applicationState?.logs?.logHeaders || {},
  );
  const [headersLoading, setHeadersLoading] = useState<boolean>(
    applicationState?.logs?.headersLoading || false,
  );

  const [selectedLogIndex, setSelectedLogIndex] = useState<number>(
    applicationState?.selectedLogIndex !== undefined
      ? applicationState.selectedLogIndex
      : -1,
  );

  const [selectedLogSummary, setSelectedLogSummary] = useState<
    EvalSummary | undefined
  >(applicationState?.selectedLogSummary);

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

  const [runningSampleData, setRunningSampleData] = useState<
    RunningSampleData | undefined
  >();

  const [selectedSampleTab, setSelectedSampleTab] = useState<
    string | undefined
  >(applicationState?.selectedSampleTab);
  const sampleScrollPosition = useRef<number>(
    applicationState?.sampleScrollPosition || 0,
  );

  // Tracks the currently loading sample index (so we can ignore subsequent requests)
  const loadingSampleIndexRef = useRef<number | null>(null);

  const workspaceTabScrollPosition = useRef<Record<string, number>>(
    applicationState?.workspaceTabScrollPosition || {},
  );

  const [showingSampleDialog, setShowingSampleDialog] = useState<boolean>(
    !!applicationState?.showingSampleDialog,
  );

  // Filtering and sorting
  const [filter, setFilter] = useState<ScoreFilter>(
    applicationState?.filter || {},
  );

  const [epoch, setEpoch] = useState<string>(applicationState?.epoch || "all");
  const [sort, setSort] = useState<string>(
    applicationState?.sort || kDefaultSort,
  );

  const [score, setScore] = useState<ScoreLabel | undefined>(
    applicationState?.score,
  );

  const [pendingSampleSummaries, setPendingSampleSummaries] =
    useState<PendingSamples>({
      samples: [],
      refresh: 2,
    });

  const saveState = useCallback(() => {
    const state = {
      selectedLogIndex,
      logHeaders,
      headersLoading,
      selectedLogSummary,
      selectedSampleIndex,
      selectedWorkspaceTab,
      selectedSample,
      sampleStatus,
      sampleError,
      selectedSampleTab,
      showingSampleDialog,
      status,
      filter,
      epoch,
      sort,
      score,
      sampleScrollPosition: sampleScrollPosition.current,
      workspaceTabScrollPosition: workspaceTabScrollPosition.current,
      ...appContext.getState(),
      ...logsContext.getState(),
    };
    if (saveApplicationState) {
      saveApplicationState(state);
    }
  }, [
    selectedLogIndex,
    logHeaders,
    headersLoading,
    selectedLogSummary,
    selectedSampleIndex,
    selectedWorkspaceTab,
    selectedSample,
    sampleStatus,
    sampleError,
    selectedSampleTab,
    showingSampleDialog,
    status,
    appContext.getState,
    logsContext.getState,
    filter,
    epoch,
    sort,
    score,
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
    selectedLogIndex,
    logHeaders,
    headersLoading,
    selectedLogSummary,
    selectedSampleIndex,
    selectedWorkspaceTab,
    selectedSample,
    sampleStatus,
    sampleError,
    selectedSampleTab,
    showingSampleDialog,
    status,
    appContext.getState,
    logsContext.getState,
    filter,
    epoch,
    sort,
    score,
  ]);

  // Function to merge log samples with pending samples
  const mergeSampleSummaries = useCallback(
    (
      logSamples: SampleSummary[],
      pendingSamples: SampleSummary[],
    ): SampleSummary[] => {
      // Create a map of existing sample IDs to avoid duplicates
      const existingSampleIds = new Set(
        logSamples.map((sample) => `${sample.id}-${sample.epoch}`),
      );

      // Filter out any pending samples that already exist in the log
      const uniquePendingSamples = pendingSamples.filter(
        (sample) => !existingSampleIds.has(`${sample.id}-${sample.epoch}`),
      );

      // Combine and return all samples
      return [...logSamples, ...uniquePendingSamples];
    },
    [],
  );

  const sampleSummaries = useMemo(() => {
    const logSamples = selectedLogSummary?.sampleSummaries || [];
    const pendingSamples = pendingSampleSummaries.samples || [];
    const result = mergeSampleSummaries(logSamples, pendingSamples);
    return result;
  }, [selectedLogSummary?.sampleSummaries, pendingSampleSummaries.samples]);

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

  const scores = useMemo(() => {
    if (!selectedLogSummary) {
      return [];
    }

    return getAvailableScorers(selectedLogSummary, sampleSummaries) || [];
  }, [selectedLogSummary, sampleSummaries]);

  const evalDescriptor = useMemo(() => {
    const result = createEvalDescriptor(scores, sampleSummaries);
    return result;
  }, [selectedLogSummary, sampleSummaries, scores]);

  const currentScore = useMemo(() => {
    if (score) {
      return score;
    } else if (selectedLogSummary) {
      return getDefaultScorer(selectedLogSummary, sampleSummaries);
    }
  }, [selectedLogSummary, sampleSummaries]);

  const samplesDescriptor = useMemo(() => {
    if (!selectedLogSummary) {
      return undefined;
    }
    const descriptor = evalDescriptor
      ? createSamplesDescriptor(sampleSummaries, evalDescriptor, currentScore)
      : undefined;
    return descriptor;
  }, [evalDescriptor, score, selectedLogSummary, sampleSummaries]);

  const filteredSamples = useMemo(() => {
    const samples = sampleSummaries || [];

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
      const sorted = sortSamples(
        sort,
        filtered,
        samplesDescriptor,
        currentScore,
      );
      return sorted;
    } else {
      return filtered;
    }
  }, [
    sampleSummaries,
    evalDescriptor,
    samplesDescriptor,
    filter,
    sort,
    currentScore,
  ]);

  const groupBy = useMemo(() => {
    // Set the grouping
    let grouping: "none" | "epoch" | "sample" = "none";
    if (
      selectedLogSummary?.eval?.config?.epochs &&
      (selectedLogSummary?.eval?.config?.epochs || 1) > 1
    ) {
      if (byEpoch(sort) || epoch !== "all") {
        grouping = "epoch";
      } else if (bySample(sort)) {
        grouping = "sample";
      }
    }
    return grouping;
  }, [samplesDescriptor]);

  const groupByOrder = useMemo(() => {
    return sort === kSampleAscVal ||
      sort === kEpochAscVal ||
      sort === kScoreAscVal
      ? "asc"
      : "desc";
  }, [sort]);

  useEffect(() => {
    const newTab =
      selectedSample?.events?.length || 0 > 0
        ? kSampleTranscriptTabId
        : kSampleMessagesTabId;
    if (selectedSampleTab === undefined && selectedSample) {
      setSelectedSampleTab(newTab);
    }
  }, [selectedSample, selectedSampleTab]);

  const loadSample = useCallback(
    async (summary: SampleSummary) => {
      if (loadingSampleIndexRef.current === selectedSampleIndex) {
        return;
      }

      const logFile = logsContext.state.logs.files[selectedLogIndex];
      if (!logFile) {
        return;
      }

      loadingSampleIndexRef.current = selectedSampleIndex;
      setSampleStatus("loading");
      setSampleError(undefined);

      try {
        // If a sample is completed, but we're still polling,
        // this means that the sample hasn't been flushed, so we should
        // continue to show the live view until the sample is flushed
        if (summary.completed !== false && !samplePollingRef.current) {
          const sample = await api.get_log_sample(
            logFile.name,
            summary.id,
            summary.epoch,
          );
          if (sample) {
            const migratedSample = migrateOldSample(sample);
            sampleScrollPosition.current = 0;
            setSelectedSample(migratedSample);
          } else {
            throw new Error(
              "Unable to load sample - an unknown error occurred.",
            );
          }
        } else {
          pollForSampleData(logFile.name, summary);
        }

        setSampleStatus("ok");
      } catch (e) {
        handleSampleLoadError(e);
      } finally {
        loadingSampleIndexRef.current = null;
      }
    },
    [logsContext.state.logs, selectedLogIndex],
  );

  const samplePollingRef = useRef<Timeout | null>(null);
  const samplePollInterval = 2;

  useEffect(() => {
    return () => {
      if (samplePollingRef.current) {
        clearTimeout(samplePollingRef.current);
        samplePollingRef.current = null;
      }
    };
  }, [selectedSampleIndex]);

  const pollForSampleData = useCallback(
    (logFile: string, summary: SampleSummary) => {
      // Ensure any existing polling instance is cleared before starting a new one
      if (samplePollingRef.current) {
        clearTimeout(samplePollingRef.current);
        samplePollingRef.current = null;
      }

      const poll = async () => {
        if (!api.get_log_sample_data) {
          return;
        }
        try {
          const sampleDataResponse = await api.get_log_sample_data(
            logFile,
            summary.id,
            summary.epoch,
          );
          if (
            sampleDataResponse?.status === "OK" &&
            sampleDataResponse.sampleData
          ) {
            sampleScrollPosition.current = 0;
            const adapter = sampleDataAdapter();
            adapter.addData(sampleDataResponse.sampleData);
            const runningData = { events: adapter.resolvedEvents(), summary };
            setRunningSampleData(runningData);
          } else if (sampleDataResponse?.status === "NotFound") {
            if (samplePollingRef.current) {
              clearTimeout(samplePollingRef.current);
              samplePollingRef.current = null;
            }
            return;
          }
          samplePollingRef.current = setTimeout(
            poll,
            samplePollInterval * 1000,
          );
        } catch (e) {
          // TODO: Backoff
          console.error("Error polling pending samples:", e);
          samplePollingRef.current = setTimeout(
            poll,
            Math.min(samplePollInterval * 2 * 1000, 60000),
          );
        }
      };

      poll();
    },
    [api.get_log_sample_data, setRunningSampleData],
  );

  // Helper function for old sample migration
  const migrateOldSample = (sample: any) => {
    if (sample.transcript) {
      sample.events = sample.transcript.events;
      sample.attachments = sample.transcript.content;
    }
    sample.attachments = sample.attachments || {};
    sample.input = resolveAttachments(sample.input, sample.attachments);
    sample.messages = resolveAttachments(sample.messages, sample.attachments);
    sample.events = resolveAttachments(sample.events, sample.attachments);
    sample.attachments = {};
    return sample;
  };

  // Generic error handler
  const handleSampleLoadError = (error: unknown) => {
    setSampleStatus("error");
    setSampleError(error as Error);
    sampleScrollPosition.current = 0;
    setSelectedSample(undefined);
  };

  // Clear the selected sample when log file changes
  useEffect(() => {
    if (
      !logsContext.state.logs.files[selectedLogIndex] ||
      selectedSampleIndex === -1
    ) {
      setSelectedSample(undefined);
    }
  }, [selectedSampleIndex, selectedLogIndex, logsContext.state.logs]);

  // Refresh selected sample
  const refreshSelectedSample = useCallback(
    (selectedSampleIdx: number) => {
      const sampleSummary = filteredSamples[selectedSampleIdx];
      sampleSummary ? loadSample(sampleSummary) : setSelectedSample(undefined);
    },
    [filteredSamples, loadSample],
  );

  // Load selected sample when index changes
  useEffect(() => {
    refreshSelectedSample(selectedSampleIndex);
  }, [selectedSampleIndex, refreshSelectedSample]);

  // Load a specific log file
  const loadLog = useCallback(
    async (logFileName: string) => {
      try {
        const logContents = await api.get_log_summary(logFileName);
        return logContents;
      } catch (e) {
        // Show an error
        console.log(e);
        appContext.dispatch({
          type: "SET_STATUS",
          payload: { loading: false, error: e as Error },
        });
      }
    },
    [api],
  );

  const reloadSelectedLog = useCallback(async () => {
    const targetLog = logsContext.state.logs.files[selectedLogIndex];
    if (!targetLog) return;

    const log = await loadLog(targetLog.name);
    if (log) {
      setSelectedLogSummary(log);
    }
  }, [
    logsContext.state.logs,
    selectedLogIndex,
    loadLog,
    setSelectedLogSummary,
  ]);

  // Poll for pending samples when a log is selected
  useEffect(() => {
    const logFile = logsContext.state.logs.files[selectedLogIndex];
    if (!logFile) return;

    let isActive = true;
    let pollTimeout: Timeout;
    let hadPending = false;

    // Define clearPendingSummaries inside the effect
    const clearPendingSummaries = () => {
      if (pendingSampleSummaries.samples.length > 0) {
        setPendingSampleSummaries((prev) => ({
          samples: [],
          refresh: prev.refresh,
        }));
        reloadSelectedLog();
      }
    };

    const pollPendingSamples = async () => {
      // Don't bother polling
      if (!api.get_log_pending_samples) {
        return;
      }

      try {
        const pendingSamples = await api.get_log_pending_samples(
          logFile.name,
          pendingSampleSummaries.etag,
        );

        if (!isActive) return;

        if (pendingSamples.status === "OK" && pendingSamples.pendingSamples) {
          setPendingSampleSummaries(pendingSamples.pendingSamples);
          reloadSelectedLog();
          hadPending = true;
        } else if (pendingSamples.status === "NotFound") {
          if (hadPending) {
            reloadSelectedLog();
          }
          clearPendingSummaries();

          // stop polling
          isActive = false;
        }

        if (isActive) {
          pollTimeout = setTimeout(
            pollPendingSamples,
            pendingSampleSummaries.refresh * 1000,
          );
        }
      } catch (error) {
        console.error("Error polling pending samples:", error);

        if (isActive) {
          pollTimeout = setTimeout(
            pollPendingSamples,
            Math.min(pendingSampleSummaries.refresh * 2 * 1000, 60000),
          );
        }
      }
    };

    pollPendingSamples();

    return () => {
      isActive = false;
      if (pollTimeout) {
        clearTimeout(pollTimeout);
      }
    };
  }, [
    logsContext.state.logs,
    selectedLogIndex,
    pendingSampleSummaries.etag,
    pendingSampleSummaries.refresh,
    reloadSelectedLog,
  ]);

  // Read header information for the logs
  // and then update
  useEffect(() => {
    const loadHeaders = async () => {
      setHeadersLoading(true);

      // Group into chunks
      const chunkSize = 8;
      const fileLists = [];
      for (let i = 0; i < logsContext.state.logs.files.length; i += chunkSize) {
        let chunk = logsContext.state.logs.files
          .slice(i, i + chunkSize)
          .map((log) => log.name);
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
          appContext.dispatch({
            type: "SET_STATUS",
            payload: { loading: false },
          });
        } else {
          console.log(e);
          appContext.dispatch({
            type: "SET_STATUS",
            payload: { loading: false, error: e as Error },
          });
        }
      }
      setHeadersLoading(false);
    };

    loadHeaders();
  }, [
    logsContext.state.logs,
    appContext.dispatch,
    setLogHeaders,
    setHeadersLoading,
  ]);

  /**
   * Resets the workspace tab based on the provided log's state.
   *
   * Determines whether the workspace tab should display samples or info,
   * depending on the presence of samples and the log status.
   */
  const resetWorkspace = useCallback(
    (log: EvalSummary, sampleSummaries: SampleSummary[]) => {
      // Reset the workspace tab
      const hasSamples = sampleSummaries.length > 0;
      const showSamples = hasSamples;
      setSelectedWorkspaceTab(
        log.status !== "error" && hasSamples
          ? kEvalWorkspaceTabId
          : kInfoWorkspaceTabId,
      );

      // Reset state
      setScore(undefined);

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

  const lastSelectedIndex = useRef<number>(-1);

  // Load a specific log
  useEffect(() => {
    const loadSpecificLog = async () => {
      // Don't reload the already loaded log
      if (lastSelectedIndex.current === selectedLogIndex) {
        return;
      }

      const targetLog = logsContext.state.logs.files[selectedLogIndex];
      if (targetLog) {
        try {
          appContext.dispatch({
            type: "SET_STATUS",
            payload: { loading: true, error: undefined },
          });
          const logContents = await loadLog(targetLog.name);
          if (logContents) {
            // Don't reset the workspace if this is the first
            // time loading

            // Set the log
            const log = logContents;
            setSelectedLogSummary(log);

            // Reset the workspace tab if we're changing
            // Don't do this the first time as we're restoring state
            if (lastSelectedIndex.current !== -1) {
              resetWorkspace(log, logContents.sampleSummaries);
            }

            // Remember we selected this
            lastSelectedIndex.current = selectedLogIndex;

            appContext.dispatch({
              type: "SET_STATUS",
              payload: { loading: false, error: undefined },
            });
          }
        } catch (e) {
          console.log(e);
          appContext.dispatch({
            type: "SET_STATUS",
            payload: { loading: false, error: e as Error },
          });
        }
      } else if (
        logsContext.state.logs.log_dir &&
        logsContext.state.logs.files.length === 0
      ) {
        appContext.dispatch({
          type: "SET_STATUS",
          payload: {
            loading: false,
            error: new Error(
              `No log files to display in the directory ${logsContext.state.logs.log_dir}. Are you sure this is the correct log directory?`,
            ),
          },
        });
      }
    };
    loadSpecificLog();
  }, [
    selectedLogIndex,
    logsContext.state.logs,
    setSelectedLogSummary,
    appContext.dispatch,
  ]);

  // Load the list of logs
  const loadLogs = async (): Promise<LogFiles> => {
    try {
      const result = await api.get_log_paths();

      return result;
    } catch (e) {
      // Show an error
      console.log(e);
      appContext.dispatch({
        type: "SET_STATUS",
        payload: { loading: false, error: e as Error },
      });
      return { log_dir: "", files: [] };
    }
  };

  const refreshLog = useCallback(async () => {
    try {
      appContext.dispatch({
        type: "SET_STATUS",
        payload: { loading: true, error: undefined },
      });

      const targetLog = logsContext.state.logs.files[selectedLogIndex];
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

        setSelectedLogSummary(log);

        // Reset the workspace tab
        resetWorkspace(log, sampleSummaries);

        appContext.dispatch({
          type: "SET_STATUS",
          payload: { loading: false, error: undefined },
        });
      }
    } catch (e) {
      // Show an error
      console.log(e);
      appContext.dispatch({
        type: "SET_STATUS",
        payload: { loading: false, error: e as Error },
      });
    }
  }, [
    logsContext.state.logs,
    selectedLogIndex,
    sampleSummaries,
    appContext.dispatch,
    setLogHeaders,
  ]);

  const showLogFile = useCallback(
    async (logUrl: string) => {
      const index = logsContext.state.logs.files.findIndex((val) => {
        return logUrl.endsWith(val.name);
      });
      if (index > -1) {
        setSelectedLogIndex(index);
      } else {
        const result = await loadLogs();
        const idx = result?.files.findIndex((file) => {
          return logUrl.endsWith(file.name);
        });
        logsContext.dispatch({
          type: "SET_LOGS",
          payload: result || { log_dir: "", files: [] },
        });
        setSelectedLogIndex(idx && idx > -1 ? idx : 0);
      }
    },
    [logsContext.state.logs, setSelectedLogIndex, logsContext.dispatch],
  );

  // TODO: Remove this to context
  const refreshLogList = useCallback(async () => {
    const currentLog =
      logsContext.state.logs.files[
        selectedLogIndex > -1 ? selectedLogIndex : 0
      ];
    const refreshedLogs = await loadLogs();
    logsContext.dispatch({
      type: "SET_LOGS",
      payload: refreshedLogs || { log_dir: "", files: [] },
    });

    const newIndex = refreshedLogs?.files.findIndex((file) => {
      return currentLog.name.endsWith(file.name);
    });
    if (newIndex !== undefined) {
      setSelectedLogIndex(newIndex);
    }
  }, [
    logsContext.state.logs,
    selectedLogIndex,
    setSelectedLogIndex,
    logsContext.dispatch,
  ]);

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
            if (log_dir === logsContext.state.logs.log_dir) {
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
    [logsContext.state.logs, showLogFile, refreshLogList],
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
        logsContext.dispatch({
          type: "SET_LOGS",
          payload: result,
        });

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
    };

    loadLogsAndState();
  }, [logsContext.dispatch]);

  // Configure an app envelope specific to the current state
  // if there are no log files, then don't show sidebar
  const fullScreen =
    logsContext.state.logs.files.length === 1 &&
    !logsContext.state.logs.log_dir;

  const showToggle =
    logsContext.state.logs.files.length > 1 ||
    !!logsContext.state.logs.log_dir ||
    false;

  /**
   * Determines the sample mode based on the selected log's contents.
   */
  const sampleMode = useMemo(() => {
    const totalSummaryCount =
      sampleSummaries.length + pendingSampleSummaries.samples.length;

    return totalSummaryCount === 0
      ? "none"
      : totalSummaryCount === 1
        ? "single"
        : "many";
  }, [sampleSummaries, pendingSampleSummaries]);

  return (
    <>
      {!fullScreen && selectedLogSummary ? (
        <Sidebar
          logs={logsContext.state.logs}
          logHeaders={logHeaders}
          loading={headersLoading}
          selectedIndex={selectedLogIndex}
          onSelectedIndexChanged={(index) => {
            setSelectedLogIndex(index);
            appContext.dispatch({ type: "SET_OFFCANVAS", payload: false });
          }}
        />
      ) : undefined}
      <div
        ref={mainAppRef}
        className={clsx(
          "app-main-grid",
          fullScreen ? "full-screen" : undefined,
          appContext.state.offcanvas ? "off-canvas" : undefined,
        )}
        tabIndex={0}
        onKeyDown={(e) => {
          // regular browsers user their own find
          if (!getVscodeApi()) {
            return;
          }

          if ((e.ctrlKey || e.metaKey) && e.key === "f") {
            appContext.dispatch({ type: "SET_SHOW_FIND", payload: true });
          } else if (e.key === "Escape") {
            appContext.dispatch({ type: "HIDE_FIND" });
          }
        }}
      >
        {!appContext.capabilities.nativeFind && appContext.state.showFind ? (
          <FindBand />
        ) : (
          ""
        )}
        <ProgressBar animating={appContext.state.status.loading} />
        {appContext.state.status.error ? (
          <ErrorPanel
            title="An error occurred while loading this task."
            error={appContext.state.status.error}
          />
        ) : (
          <WorkSpace
            task_id={selectedLogSummary?.eval?.task_id}
            logFileName={logsContext.state.logs.files[selectedLogIndex]?.name}
            evalStatus={selectedLogSummary?.status}
            evalError={filterNull(selectedLogSummary?.error)}
            evalVersion={selectedLogSummary?.version}
            evalSpec={selectedLogSummary?.eval}
            evalPlan={selectedLogSummary?.plan}
            evalStats={selectedLogSummary?.stats}
            evalResults={filterNull(selectedLogSummary?.results)}
            runningMetrics={pendingSampleSummaries.metrics}
            showToggle={showToggle}
            samples={filteredSamples}
            sampleMode={sampleMode}
            groupBy={groupBy}
            groupByOrder={groupByOrder}
            sampleStatus={sampleStatus}
            sampleError={sampleError}
            samplesDescriptor={samplesDescriptor}
            refreshLog={refreshLog}
            selectedSample={selectedSample}
            selectedSampleIndex={selectedSampleIndex}
            runningSampleData={runningSampleData}
            setSelectedSampleIndex={setSelectedSampleIndex}
            showingSampleDialog={showingSampleDialog}
            setShowingSampleDialog={handleSampleShowingDialog}
            selectedTab={selectedWorkspaceTab}
            setSelectedTab={setSelectedWorkspaceTab}
            selectedSampleTab={selectedSampleTab}
            setSelectedSampleTab={setSelectedSampleTab}
            sort={sort}
            setSort={setSort}
            epochs={selectedLogSummary?.eval?.config?.epochs}
            epoch={epoch}
            setEpoch={setEpoch}
            filter={filter}
            setFilter={setFilter}
            score={currentScore}
            setScore={setScore}
            scores={scores || []}
            sampleScrollPositionRef={sampleScrollPosition}
            setSampleScrollPosition={setSampleScrollPosition}
            workspaceTabScrollPositionRef={workspaceTabScrollPosition}
            setWorkspaceTabScrollPosition={setWorkspaceTabScrollPosition}
          />
        )}
      </div>
    </>
  );
};

const filterNull = <T,>(obj: T | null): T | undefined => {
  if (obj === null) {
    return undefined;
  }
  return obj;
};
