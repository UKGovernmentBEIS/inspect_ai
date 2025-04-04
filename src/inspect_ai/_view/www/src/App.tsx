import "bootstrap-icons/font/bootstrap-icons.css";
import "bootstrap/dist/css/bootstrap.css";
import JSON5 from "json5";

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

import { FindBand } from "./components/FindBand";
import { Sidebar } from "./workspace/sidebar/Sidebar.tsx";
import { WorkSpace } from "./workspace/WorkSpace";

import ClipboardJS from "clipboard";
import clsx from "clsx";
import { FC, KeyboardEvent, useCallback, useEffect, useRef } from "react";
import { ClientAPI, HostMessage } from "./api/types.ts";
import { useSetSelectedLogIndex } from "./state/hooks.ts";
import { useStore } from "./state/store.ts";

interface AppProps {
  api: ClientAPI;
}

/**
 * Renders the Main Application
 */
export const App: FC<AppProps> = ({ api }) => {
  // App layout and state
  const appStatus = useStore((state) => state.app.status);
  const setAppStatus = useStore((state) => state.appActions.setStatus);
  const offCanvas = useStore((state) => state.app.offcanvas);
  const setOffCanvas = useStore((state) => state.appActions.setOffcanvas);
  const clearWorkspaceTab = useStore(
    (state) => state.appActions.clearWorkspaceTab,
  );
  const clearSampleTab = useStore((state) => state.appActions.clearSampleTab);

  // Find
  const nativeFind = useStore((state) => state.capabilities.nativeFind);
  const showFind = useStore((state) => state.app.showFind);
  const setShowFind = useStore((state) => state.appActions.setShowFind);
  const hideFind = useStore((state) => state.appActions.hideFind);

  // Logs Data
  const logs = useStore((state) => state.logs.logs);
  const selectedLogIndex = useStore((state) => state.logs.selectedLogIndex);
  const logHeaders = useStore((state) => state.logs.logHeaders);
  const headersLoading = useStore((state) => state.logs.headersLoading);
  const setLogs = useStore((state) => state.logsActions.setLogs);
  const selectedLogFile = useStore((state) =>
    state.logsActions.getSelectedLogFile(),
  );
  const setSelectedLogIndex = useSetSelectedLogIndex();

  const refreshLogs = useStore((state) => state.logsActions.refreshLogs);
  const selectLogFile = useStore((state) => state.logsActions.selectLogFile);

  // Log Data
  const selectedLogSummary = useStore((state) => state.log.selectedLogSummary);
  const loadedLogFile = useStore((state) => state.log.loadedLog);
  const runningMetrics = useStore(
    (state) => state.log.pendingSampleSummaries?.metrics,
  );
  const resetFiltering = useStore((state) => state.logActions.resetFiltering);
  const loadLog = useStore((state) => state.logActions.loadLog);
  const pollLog = useStore((state) => state.logActions.pollLog);
  const refreshLog = useStore((state) => state.logActions.refreshLog);
  const selectSample = useStore((state) => state.logActions.selectSample);

  // The main application reference
  const mainAppRef = useRef<HTMLDivElement>(null);

  // Load a specific log
  useEffect(() => {
    const loadSpecificLog = async () => {
      if (selectedLogFile && selectedLogFile !== loadedLogFile) {
        try {
          // Set loading first and wait for it to update
          setAppStatus({ loading: true, error: undefined });

          // Then load the log
          await loadLog(selectedLogFile);
          selectSample(0);

          // Finally set loading to false
          setAppStatus({ loading: false, error: undefined });
        } catch (e) {
          console.log(e);
          setAppStatus({ loading: false, error: e as Error });
        }
      }
    };

    loadSpecificLog();
  }, [selectedLogFile, loadedLogFile, loadLog, setAppStatus]);

  useEffect(() => {
    // If the component re-mounts and there is a running load loaded
    // start up polling
    const doPoll = async () => {
      await pollLog();
    };
    if (selectedLogSummary?.status === "started") {
      doPoll();
    }
  }, []);

  useEffect(() => {
    if (logs.log_dir && logs.files.length === 0) {
      setAppStatus({
        loading: false,
        error: new Error(
          `No log files to display in the directory ${logs.log_dir}. Are you sure this is the correct log directory?`,
        ),
      });
    }
  }, [logs.log_dir, logs.files.length]);

  const appRefreshLog = useCallback(() => {
    try {
      setAppStatus({ loading: true, error: undefined });

      refreshLog();
      resetFiltering();

      setAppStatus({ loading: false, error: undefined });
    } catch (e) {
      // Show an error
      console.log(e);
      setAppStatus({ loading: false, error: e as Error });
    }
  }, [refreshLog, resetFiltering, setAppStatus]);

  const onMessage = useCallback(
    async (e: HostMessage) => {
      switch (e.data.type) {
        case "updateState": {
          if (e.data.url) {
            const decodedUrl = decodeURIComponent(e.data.url);
            selectLogFile(decodedUrl);
          }
          break;
        }
        case "backgroundUpdate": {
          const decodedUrl = decodeURIComponent(e.data.url);
          const log_dir = e.data.log_dir;
          const isFocused = document.hasFocus();
          if (!isFocused) {
            if (log_dir === logs.log_dir) {
              selectLogFile(decodedUrl);
            } else {
              api.open_log_file(e.data.url, e.data.log_dir);
            }
          } else {
            refreshLogs();
          }
          break;
        }
      }
    },
    [logs, selectLogFile, refreshLogs],
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
        const state = JSON5.parse(embeddedState.textContent || "");
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
          setLogs({
            log_dir: "",
            files: [{ name: resolvedLogPath }],
          });
        } else {
          // If a log file was passed, select it
          const log_file = urlParams.get("log_file");
          if (log_file) {
            await selectLogFile(log_file);
          } else {
            // Load all logs
            await refreshLogs();
          }
        }
      }

      new ClipboardJS(".clipboard-button,.copy-button");
    };

    loadLogsAndState();
  }, [setLogs, selectLogFile, refreshLogs]);

  // Configure an app envelope specific to the current state
  // if there are no log files, then don't show sidebar
  const fullScreen = logs.files.length === 1 && !logs.log_dir;

  const showToggle = logs.files.length > 1 || !!logs.log_dir || false;

  const handleSelectedIndexChanged = useCallback(
    (index: number) => {
      setSelectedLogIndex(index);
      setOffCanvas(false);
      resetFiltering();
      clearSampleTab();
      clearWorkspaceTab();
      selectSample(0);
    },
    [
      setSelectedLogIndex,
      setOffCanvas,
      resetFiltering,
      clearSampleTab,
      clearWorkspaceTab,
      selectSample,
    ],
  );

  const handleKeyboard = useCallback(
    (e: KeyboardEvent) => {
      // Add keyboard shortcuts for find, if needed
      if (nativeFind || !setShowFind) {
        return;
      }

      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        setShowFind(true);
      } else if (e.key === "Escape") {
        hideFind();
      }
    },
    [nativeFind, setShowFind, hideFind],
  );

  return (
    <>
      {!fullScreen && selectedLogSummary ? (
        <Sidebar
          logs={logs}
          logHeaders={logHeaders}
          loading={headersLoading}
          selectedIndex={selectedLogIndex}
          onSelectedIndexChanged={handleSelectedIndexChanged}
        />
      ) : undefined}
      <div
        ref={mainAppRef}
        className={clsx(
          "app-main-grid",
          fullScreen ? "full-screen" : undefined,
          offCanvas ? "off-canvas" : undefined,
        )}
        tabIndex={0}
        onKeyDown={handleKeyboard}
      >
        {!nativeFind && showFind ? <FindBand /> : ""}
        <ProgressBar animating={appStatus.loading} />
        {appStatus.error ? (
          <ErrorPanel
            title="An error occurred while loading this task."
            error={appStatus.error}
          />
        ) : (
          <WorkSpace
            task_id={selectedLogSummary?.eval?.task_id}
            evalStatus={selectedLogSummary?.status}
            evalError={filterNull(selectedLogSummary?.error)}
            evalVersion={selectedLogSummary?.version}
            evalSpec={selectedLogSummary?.eval}
            evalPlan={selectedLogSummary?.plan}
            evalStats={selectedLogSummary?.stats}
            evalResults={filterNull(selectedLogSummary?.results)}
            runningMetrics={runningMetrics}
            showToggle={showToggle}
            refreshLog={appRefreshLog}
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
