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
import { ClientAPI, HostMessage } from "./api/types.ts";
import {
  kEvalWorkspaceTabId,
  kInfoWorkspaceTabId,
  kSampleMessagesTabId,
  kSampleTranscriptTabId,
} from "./constants";
import { useLogsStore, useSelectedLogFile } from "./state/logsStore.ts";
import { useLogStore, useTotalSampleCount } from "./state/logStore.ts";
import { useSampleStore } from "./state/sampleStore.ts";
import { useStore } from "./state/store.ts";
import { ApplicationState } from "./types.ts";

interface AppProps {
  api: ClientAPI;
  applicationState?: ApplicationState;
  saveApplicationState?: (state: ApplicationState) => void;
}

/**
 * Renders the Main Application
 */
export const App: FC<AppProps> = ({ api, applicationState }) => {
  // Application Context

  const logsStore = useLogsStore();
  const logStore = useLogStore();

  // App layout and state
  const appStatus = useStore((state) => state.app.status);
  const setAppStatus = useStore((state) => state.appActions.setStatus);
  const offCanvas = useStore((state) => state.app.offcanvas);
  const setOffCanvas = useStore((state) => state.appActions.setOffcanvas);

  // Find
  const nativeFind = useStore((state) => state.capabilities.nativeFind);
  const showFind = useStore((state) => state.app.showFind);
  const setShowFind = useStore((state) => state.appActions.setShowFind);
  const hideFind = useStore((state) => state.appActions.hideFind);

  const clearSelectedSample = useSampleStore(
    (state) => state.clearSelectedSample,
  );
  const selectedSample = useSampleStore((state) => state.selectedSample);

  const selectedLogFile = useSelectedLogFile();

  // The main application reference
  const mainAppRef = useRef<HTMLDivElement>(null);

  // Workspace (the selected tab)
  const [selectedWorkspaceTab, setSelectedWorkspaceTab] = useState<string>(
    applicationState?.selectedWorkspaceTab || kEvalWorkspaceTabId,
  );

  const [selectedSampleTab, setSelectedSampleTab] = useState<
    string | undefined
  >(applicationState?.selectedSampleTab);
  const sampleScrollPosition = useRef<number>(
    applicationState?.sampleScrollPosition || 0,
  );

  const workspaceTabScrollPosition = useRef<Record<string, number>>(
    applicationState?.workspaceTabScrollPosition || {},
  );

  const [showingSampleDialog, setShowingSampleDialog] = useState<boolean>(
    !!applicationState?.showingSampleDialog,
  );

  const setSampleScrollPosition = useCallback(
    debounce((position) => {
      sampleScrollPosition.current = position;
      // TODO Save state somehow
      // saveStateRef.current();
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
        // TODO Save state somehow
      }
    }, 1000),
    [],
  );

  // Save state when it changes, so that we can restore it later
  //
  useEffect(() => {
    // TODO Save state somehow
  }, [selectedWorkspaceTab, selectedSampleTab, showingSampleDialog]);

  const handleSampleShowingDialog = useCallback(
    (show: boolean) => {
      setShowingSampleDialog(show);
    },
    [setShowingSampleDialog],
  );

  useEffect(() => {
    if (!showingSampleDialog) {
      clearSelectedSample();
      setSelectedSampleTab(undefined);
    }
  }, [showingSampleDialog, clearSelectedSample, setSelectedSampleTab]);

  useEffect(() => {
    if (!selectedSample) return;

    const newTab =
      (selectedSample.events?.length || 0) > 0
        ? kSampleTranscriptTabId
        : kSampleMessagesTabId;

    if (selectedSampleTab === undefined) {
      setSelectedSampleTab(newTab);
    }
  }, [selectedSample, selectedSampleTab]);

  // Clear the selected sample when log file changes
  useEffect(() => {
    if (
      !logsStore.logs.files[logsStore.selectedLogIndex] ||
      logStore.selectedSampleIndex === -1
    ) {
      clearSelectedSample();
    }
  }, [
    logStore.selectedSampleIndex,
    logsStore.selectedLogIndex,
    logsStore.logs,
    clearSelectedSample,
  ]);

  useEffect(() => {
    logStore.selectSample(0);
  }, [selectedLogFile, logStore.selectSample]);

  // Load a specific log
  useEffect(() => {
    const loadSpecificLog = async () => {
      if (selectedLogFile) {
        try {
          // Set loading first and wait for it to update
          setAppStatus({ loading: true, error: undefined });

          // Then load the log
          await logStore.loadLog(selectedLogFile);

          // Finally set loading to false
          setAppStatus({ loading: false, error: undefined });
        } catch (e) {
          console.log(e);
          setAppStatus({ loading: false, error: e as Error });
        }
      }
    };
    loadSpecificLog();
  }, [selectedLogFile, logStore.loadLog, setAppStatus]);

  useEffect(() => {
    // Reset the workspace
    setSelectedWorkspaceTab(kEvalWorkspaceTabId);

    // Reset the sample tab
    setSelectedSampleTab(undefined);

    workspaceTabScrollPosition.current = {};

    clearSelectedSample();
  }, [logStore.selectedLogSummary?.eval.task_id, clearSelectedSample]);

  const totalSampleCount = useTotalSampleCount();
  useEffect(() => {
    if (logStore.selectedLogSummary && totalSampleCount === 0) {
      setSelectedWorkspaceTab(kInfoWorkspaceTabId);
    }
  }, [logStore.selectedLogSummary]);

  useEffect(() => {
    if (logsStore.logs.log_dir && logsStore.logs.files.length === 0) {
      setAppStatus({
        loading: false,
        error: new Error(
          `No log files to display in the directory ${logsStore.logs.log_dir}. Are you sure this is the correct log directory?`,
        ),
      });
    }
  }, [logsStore.logs.log_dir, logsStore.logs.files.length]);

  const refreshLog = useCallback(() => {
    try {
      setAppStatus({ loading: true, error: undefined });

      logStore.refreshLog();
      logStore.resetFiltering();

      setAppStatus({ loading: false, error: undefined });
    } catch (e) {
      // Show an error
      console.log(e);
      setAppStatus({ loading: false, error: e as Error });
    }
  }, [logStore.refreshLog, logStore.resetFiltering, setAppStatus]);

  const onMessage = useCallback(
    async (e: HostMessage) => {
      switch (e.data.type) {
        case "updateState": {
          if (e.data.url) {
            const decodedUrl = decodeURIComponent(e.data.url);
            logsStore.selectLogFile(decodedUrl);
          }
          break;
        }
        case "backgroundUpdate": {
          const decodedUrl = decodeURIComponent(e.data.url);
          const log_dir = e.data.log_dir;
          const isFocused = document.hasFocus();
          if (!isFocused) {
            if (log_dir === logsStore.logs.log_dir) {
              logsStore.selectLogFile(decodedUrl);
            } else {
              api.open_log_file(e.data.url, e.data.log_dir);
            }
          } else {
            logsStore.refreshLogs();
          }
          break;
        }
      }
    },
    [logsStore.logs, logsStore.selectLogFile, logsStore.refreshLogs],
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
          logsStore.setLogs({
            log_dir: "",
            files: [{ name: resolvedLogPath }],
          });
        } else {
          // If a log file was passed, select it
          const log_file = urlParams.get("log_file");
          if (log_file) {
            await logsStore.selectLogFile(log_file);
          } else {
            // Load all logs
            await logsStore.refreshLogs();
          }
        }
      }

      new ClipboardJS(".clipboard-button,.copy-button");
    };

    loadLogsAndState();
  }, [logsStore.setLogs, logsStore.selectLogFile, logsStore.refreshLogs]);

  // Configure an app envelope specific to the current state
  // if there are no log files, then don't show sidebar
  const fullScreen =
    logsStore.logs.files.length === 1 && !logsStore.logs.log_dir;

  const showToggle =
    logsStore.logs.files.length > 1 || !!logsStore.logs.log_dir || false;

  return (
    <>
      {!fullScreen && logStore.selectedLogSummary ? (
        <Sidebar
          logs={logsStore.logs}
          logHeaders={logsStore.logHeaders}
          loading={logsStore.headersLoading}
          selectedIndex={logsStore.selectedLogIndex}
          onSelectedIndexChanged={(index) => {
            logsStore.setSelectedLogIndex(index);
            setOffCanvas(false);
          }}
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
        onKeyDown={(e) => {
          console.log("KEYB");
          console.log({ nativeFind, showFind });
          // Add keyboard shortcuts for find, if needed
          if (nativeFind || !setShowFind) {
            return;
          }

          if ((e.ctrlKey || e.metaKey) && e.key === "f") {
            console.log("SET SHOW FIND");
            setShowFind(true);
          } else if (e.key === "Escape") {
            hideFind();
          }
        }}
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
            task_id={logStore.selectedLogSummary?.eval?.task_id}
            evalStatus={logStore.selectedLogSummary?.status}
            evalError={filterNull(logStore.selectedLogSummary?.error)}
            evalVersion={logStore.selectedLogSummary?.version}
            evalSpec={logStore.selectedLogSummary?.eval}
            evalPlan={logStore.selectedLogSummary?.plan}
            evalStats={logStore.selectedLogSummary?.stats}
            evalResults={filterNull(logStore.selectedLogSummary?.results)}
            runningMetrics={logStore.pendingSampleSummaries?.metrics}
            showToggle={showToggle}
            refreshLog={refreshLog}
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
