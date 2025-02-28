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
import { debounce } from "./utils/sync";

import { FindBand } from "./components/FindBand";
import { Sidebar } from "./workspace/sidebar/Sidebar.tsx";
import { WorkSpace } from "./workspace/WorkSpace";

import ClipboardJS from "clipboard";
import clsx from "clsx";
import { FC, useCallback, useEffect, useRef, useState } from "react";
import { ClientAPI, HostMessage, SampleSummary } from "./api/types.ts";
import {
  kEvalWorkspaceTabId,
  kInfoWorkspaceTabId,
  kSampleMessagesTabId,
  kSampleTranscriptTabId,
} from "./constants";
import { useAppContext } from "./contexts/AppContext.tsx";
import { useLogContext } from "./contexts/LogContext.tsx";
import { useLogsContext } from "./contexts/LogsContext.tsx";
import { sampleDataAdapter } from "./samples/sampleDataAdapter.ts";
import { ApplicationState, RunningSampleData } from "./types.ts";
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
  const logContext = useLogContext();

  // The main application reference
  const mainAppRef = useRef<HTMLDivElement>(null);

  // Workspace (the selected tab)
  const [selectedWorkspaceTab, setSelectedWorkspaceTab] = useState<string>(
    applicationState?.selectedWorkspaceTab || kEvalWorkspaceTabId,
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

  const saveState = useCallback(() => {
    const state = {
      selectedWorkspaceTab,
      selectedSample,
      sampleStatus,
      sampleError,
      selectedSampleTab,
      showingSampleDialog,
      status,
      sampleScrollPosition: sampleScrollPosition.current,
      workspaceTabScrollPosition: workspaceTabScrollPosition.current,
      ...appContext.getState(),
      ...logsContext.getState(),
      ...logContext.getState(),
    };
    if (saveApplicationState) {
      saveApplicationState(state);
    }
  }, [
    selectedWorkspaceTab,
    selectedSample,
    sampleStatus,
    sampleError,
    selectedSampleTab,
    showingSampleDialog,
    status,
    appContext.getState,
    logsContext.getState,
    logContext.getState,
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
    selectedWorkspaceTab,
    selectedSample,
    sampleStatus,
    sampleError,
    selectedSampleTab,
    showingSampleDialog,
    status,
    appContext.getState,
    logsContext.getState,
    logContext.getState,
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
      if (
        loadingSampleIndexRef.current === logContext.state.selectedSampleIndex
      ) {
        return;
      }

      const logFile =
        logsContext.state.logs.files[logsContext.state.selectedLogIndex];
      if (!logFile) {
        return;
      }

      loadingSampleIndexRef.current = logContext.state.selectedSampleIndex;
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
    [logsContext.state.logs, logsContext.state.selectedLogIndex],
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
  }, [logContext.state.selectedSampleIndex]);

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
      !logsContext.state.logs.files[logsContext.state.selectedLogIndex] ||
      logContext.state.selectedSampleIndex === -1
    ) {
      setSelectedSample(undefined);
    }
  }, [
    logContext.state.selectedSampleIndex,
    logsContext.state.selectedLogIndex,
    logsContext.state.logs,
  ]);

  // Refresh selected sample
  const refreshSelectedSample = useCallback(
    (selectedSampleIdx: number) => {
      const sampleSummary = logContext.sampleSummaries[selectedSampleIdx];
      sampleSummary ? loadSample(sampleSummary) : setSelectedSample(undefined);
    },
    [logContext.sampleSummaries, loadSample],
  );

  // Load selected sample when index changes
  useEffect(() => {
    refreshSelectedSample(logContext.state.selectedSampleIndex);
  }, [logContext.state.selectedSampleIndex, refreshSelectedSample]);

  useEffect(() => {
    if (logContext.totalSampleCount) {
      logContext.dispatch({ type: "SELECT_SAMPLE", payload: 0 });
    }
  }, [logContext.totalSampleCount]);

  // Load a specific log
  useEffect(() => {
    const loadSpecificLog = async () => {
      if (logsContext.selectedLogFile) {
        try {
          appContext.dispatch({
            type: "SET_STATUS",
            payload: { loading: true, error: undefined },
          });
          await logContext.loadLog(logsContext.selectedLogFile);
          appContext.dispatch({
            type: "SET_STATUS",
            payload: { loading: false, error: undefined },
          });
        } catch (e) {
          console.log(e);
          appContext.dispatch({
            type: "SET_STATUS",
            payload: { loading: false, error: e as Error },
          });
        }
      }
    };
    loadSpecificLog();
  }, [logsContext.selectedLogFile, logContext.dispatch, appContext.dispatch]);

  useEffect(() => {
    // Reset the workspace
    setSelectedWorkspaceTab(kEvalWorkspaceTabId);

    // Reset the sample tab
    setSelectedSampleTab(undefined);
    setSelectedSample(undefined);
    workspaceTabScrollPosition.current = {};
  }, [logContext.state.selectedLogSummary?.eval.task_id]);

  useEffect(() => {
    if (logContext.totalSampleCount === 0) {
      setSelectedWorkspaceTab(kInfoWorkspaceTabId);
    }
  }, [logContext.totalSampleCount]);

  useEffect(() => {
    if (
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
  }, [logsContext.state.logs.log_dir, logsContext.state.logs.files.length]);

  const refreshLog = useCallback(() => {
    try {
      appContext.dispatch({
        type: "SET_STATUS",
        payload: { loading: true, error: undefined },
      });

      logContext.refreshLog();
      logContext.dispatch({ type: "RESET_FILTERING" });

      appContext.dispatch({
        type: "SET_STATUS",
        payload: { loading: false, error: undefined },
      });
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
    logsContext.state.selectedLogIndex,
    logContext.refreshLog,
    logContext.dispatch,
    appContext.dispatch,
  ]);

  const onMessage = useCallback(
    async (e: HostMessage) => {
      switch (e.data.type) {
        case "updateState": {
          if (e.data.url) {
            const decodedUrl = decodeURIComponent(e.data.url);
            logsContext.selectLogFile(decodedUrl);
          }
          break;
        }
        case "backgroundUpdate": {
          const decodedUrl = decodeURIComponent(e.data.url);
          const log_dir = e.data.log_dir;
          const isFocused = document.hasFocus();
          if (!isFocused) {
            if (log_dir === logsContext.state.logs.log_dir) {
              logsContext.selectLogFile(decodedUrl);
            } else {
              api.open_log_file(e.data.url, e.data.log_dir);
            }
          } else {
            logsContext.refreshLogs();
          }
          break;
        }
      }
    },
    [
      logsContext.state.logs,
      logsContext.selectLogFile,
      logsContext.refreshLogs,
    ],
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
      // First see if there is embedded state and if so, use that
      const embeddedState = document.getElementById("logview-state");
      if (embeddedState) {
        const state = JSON.parse(embeddedState.textContent || "");
        onMessage({ data: state });
      } else {
        // See whether a specific task_file has been passed.
        const urlParams = new URLSearchParams(window.location.search);

        // If the URL provides a task file, load that
        const logPath = urlParams.get("task_file");

        // Replace spaces with a '+' sign:
        const resolvedLogPath = logPath ? logPath.replace(" ", "+") : logPath;

        if (resolvedLogPath) {
          // Load only this file
          logsContext.dispatch({
            type: "SET_LOGS",
            payload: {
              log_dir: "",
              files: [{ name: resolvedLogPath }],
            },
          });
        } else {
          // If a log file was passed, select it
          const log_file = urlParams.get("log_file");
          if (log_file) {
            await logsContext.selectLogFile(log_file);
          } else {
            // Load all logs
            await logsContext.refreshLogs();
          }
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
  const sampleMode =
    logContext.totalSampleCount === 0
      ? "none"
      : logContext.totalSampleCount === 1
        ? "single"
        : "many";

  return (
    <>
      {!fullScreen && logContext.state.selectedLogSummary ? (
        <Sidebar
          logs={logsContext.state.logs}
          logHeaders={logsContext.state.logHeaders}
          loading={logsContext.state.headersLoading}
          selectedIndex={logsContext.state.selectedLogIndex}
          onSelectedIndexChanged={(index) => {
            logsContext.dispatch({
              type: "SET_SELECTED_LOG_INDEX",
              payload: index,
            });
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
          // Add keyboard shortcuts for find, if needed
          if (
            appContext.capabilities.nativeFind ||
            !appContext.state.showFind
          ) {
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
            task_id={logContext.state.selectedLogSummary?.eval?.task_id}
            logFileName={logsContext.selectedLogFile}
            evalStatus={logContext.state.selectedLogSummary?.status}
            evalError={filterNull(logContext.state.selectedLogSummary?.error)}
            evalVersion={logContext.state.selectedLogSummary?.version}
            evalSpec={logContext.state.selectedLogSummary?.eval}
            evalPlan={logContext.state.selectedLogSummary?.plan}
            evalStats={logContext.state.selectedLogSummary?.stats}
            evalResults={filterNull(
              logContext.state.selectedLogSummary?.results,
            )}
            runningMetrics={logContext.state.pendingSampleSummaries?.metrics}
            showToggle={showToggle}
            samples={logContext.sampleSummaries}
            sampleMode={sampleMode}
            sampleStatus={sampleStatus}
            sampleError={sampleError}
            refreshLog={refreshLog}
            selectedSample={selectedSample}
            runningSampleData={runningSampleData}
            showingSampleDialog={showingSampleDialog}
            setShowingSampleDialog={handleSampleShowingDialog}
            selectedTab={selectedWorkspaceTab}
            setSelectedTab={setSelectedWorkspaceTab}
            selectedSampleTab={selectedSampleTab}
            setSelectedSampleTab={setSelectedSampleTab}
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
