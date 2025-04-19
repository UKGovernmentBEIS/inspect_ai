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

import "./App.css";

import ClipboardJS from "clipboard";
import { FC, useCallback, useEffect } from "react";
import { RouterProvider } from "react-router-dom";
import { ClientAPI, HostMessage } from "../client/api/types.ts";
import { useStore } from "../state/store.ts";
import { AppRouter } from "./routing/AppRouter.tsx";

interface AppProps {
  api: ClientAPI;
}

/**
 * Renders the Main Application
 */
export const App: FC<AppProps> = ({ api }) => {
  const setAppStatus = useStore((state) => state.appActions.setStatus);
  const setLogs = useStore((state) => state.logsActions.setLogs);
  const selectLogFile = useStore((state) => state.logsActions.selectLogFile);
  const setIntialState = useStore((state) => state.appActions.setInitialState);
  const rehydrated = useStore((state) => state.app.rehydrated);
  const refreshLogs = useStore((state) => state.logsActions.refreshLogs);
  const loadLog = useStore((state) => state.logActions.loadLog);
  const pollLog = useStore((state) => state.logActions.pollLog);
  const loadedLogFile = useStore((state) => state.log.loadedLog);
  const selectedLogFile = useStore((state) =>
    state.logsActions.getSelectedLogFile(),
  );
  const selectedLogSummary = useStore((state) => state.log.selectedLogSummary);
  const logs = useStore((state) => state.logs.logs);

  // Load a specific log
  useEffect(() => {
    const loadSpecificLog = async () => {
      if (selectedLogFile && selectedLogFile !== loadedLogFile) {
        try {
          // Set loading first and wait for it to update
          setAppStatus({ loading: true, error: undefined });

          // Then load the log
          await loadLog(selectedLogFile);

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
  }, [pollLog, selectedLogSummary?.status]);

  useEffect(() => {
    if (logs.log_dir && logs.files.length === 0) {
      setAppStatus({
        loading: false,
        error: new Error(
          `No log files to display in the directory ${logs.log_dir}. Are you sure this is the correct log directory?`,
        ),
      });
    }
  }, [logs.log_dir, logs.files.length, setAppStatus]);

  const onMessage = useCallback(
    async (e: HostMessage) => {
      switch (e.data.type) {
        case "updateState": {
          if (e.data.url) {
            const decodedUrl = decodeURIComponent(e.data.url);
            setIntialState(decodedUrl, e.data.sample_id, e.data.sample_epoch);
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
    [logs, selectLogFile, refreshLogs, api],
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
      if (embeddedState && !rehydrated) {
        const state = JSON5.parse(embeddedState.textContent || "");
        onMessage({ data: state });
      } else {
        // For non-route URL params support (legacy)
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
          }
          // Else do nothing - RouteProvider will handle it
        }
      }

      new ClipboardJS(".clipboard-button,.copy-button");
    };

    loadLogsAndState();
  }, [setLogs, selectLogFile, refreshLogs, onMessage]);

  return <RouterProvider router={AppRouter} />;
};
