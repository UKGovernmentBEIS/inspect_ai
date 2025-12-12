import "bootstrap-icons/font/bootstrap-icons.css";
import "bootstrap/dist/css/bootstrap.css";
import JSON5 from "json5";

import "prismjs";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-clike";
import "prismjs/components/prism-javascript";
import "prismjs/components/prism-json";
import "prismjs/components/prism-python";
import "prismjs/components/prism-yaml";
import "prismjs/themes/prism.css";
import "./App.css";

import ClipboardJS from "clipboard";
import { FC, useCallback, useEffect } from "react";
import { RouterProvider } from "react-router-dom";
import { ClientAPI, HostMessage } from "../client/api/types.ts";
import { useStore } from "../state/store.ts";
import { basename, dirname } from "../utils/path.ts";
import { isUri } from "../utils/uri.ts";
import { AppRouter } from "./routing/AppRouter.tsx";

interface AppProps {
  api: ClientAPI;
}

/**
 * Renders the Main Application
 */
export const App: FC<AppProps> = ({ api }) => {
  // Whether the app was rehydrated
  const rehydrated = useStore((state) => state.app.rehydrated);

  const logDir = useStore((state) => state.logs.logDir);
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  const loadedLogFile = useStore((state) => state.log.loadedLog);
  const selectedLogDetails = useStore((state) => state.log.selectedLogDetails);

  const setInitialState = useStore((state) => state.appActions.setInitialState);
  const setLoading = useStore((state) => state.appActions.setLoading);

  const syncLogs = useStore((state) => state.logsActions.syncLogs);
  const setLogDir = useStore((state) => state.logsActions.setLogDir);
  const setLogFiles = useStore((state) => state.logsActions.setLogHandles);
  const setSelectedLogFile = useStore(
    (state) => state.logsActions.setSelectedLogFile,
  );

  const loadLog = useStore((state) => state.logActions.syncLog);
  const pollLog = useStore((state) => state.logActions.pollLog);

  const setSingleFileMode = useStore(
    (state) => state.appActions.setSingleFileMode,
  );

  // Load a specific log
  useEffect(() => {
    const loadSpecificLog = async () => {
      // Ignore if there is no log file.
      if (!selectedLogFile) {
        return;
      }

      if (selectedLogFile === loadedLogFile && selectedLogDetails) {
        // The log is already loaded and we have the data
        return;
      }

      try {
        // Set loading first and wait for it to update
        setLoading(true);

        // Then load the log
        await loadLog(selectedLogFile);

        // Finally set loading to false
        setLoading(false);
      } catch (e) {
        console.log(e);
        setLoading(false, e as Error);
      }
    };

    loadSpecificLog();
  }, [selectedLogFile, loadedLogFile, selectedLogDetails, loadLog, setLoading]);

  useEffect(() => {
    // If the component re-mounts and there is a running load loaded
    // start up polling
    const doPoll = async () => {
      await pollLog();
    };
    if (selectedLogDetails?.status === "started") {
      doPoll();
    }
  }, [pollLog, selectedLogDetails?.status]);

  const onMessage = useCallback(
    async (e: HostMessage) => {
      switch (e.data.type) {
        case "updateState": {
          if (e.data.url) {
            const decodedUrl = decodeURIComponent(e.data.url);

            let targetFile = decodedUrl;
            if (isUri(targetFile)) {
              // If it's a URI, just set the log file directly
              const dir = dirname(targetFile);
              targetFile = basename(targetFile);
              setLogDir(dir);
            }

            setInitialState(targetFile, e.data.sample_id, e.data.sample_epoch);
          }
          break;
        }
        case "backgroundUpdate": {
          const decodedUrl = decodeURIComponent(e.data.url);
          const log_dir = e.data.log_dir;
          const isFocused = document.hasFocus();
          if (!isFocused) {
            if (log_dir === logDir) {
              setSelectedLogFile(decodedUrl);
            } else {
              api.open_log_file(e.data.url, e.data.log_dir);
            }
          } else {
            syncLogs();
          }
          break;
        }
      }
    },
    [setInitialState, setLogDir, logDir, setSelectedLogFile, api, syncLogs],
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
        setSingleFileMode(true);
      } else {
        // For non-route URL params support (legacy)
        const urlParams = new URLSearchParams(window.location.search);

        // If the URL provides a task file, load that
        const logPath = urlParams.get("task_file");

        // Replace spaces with a '+' sign:
        const resolvedLogPath = logPath ? logPath.replace(" ", "+") : logPath;

        if (resolvedLogPath) {
          // Clear any log dir
          setLogDir(undefined);
          // Load just the passed file
          setLogFiles([{ name: resolvedLogPath }]);
          setSingleFileMode(true);
        } else {
          // If a log file was passed, select it
          const log_file = urlParams.get("log_file");
          if (log_file) {
            setSelectedLogFile(log_file);
            setSingleFileMode(true);
          }
          // Else do nothing - RouteProvider will handle it
        }
      }

      new ClipboardJS(".clipboard-button,.copy-button");
    };

    loadLogsAndState();
  }, [
    setLogDir,
    setLogFiles,
    setSelectedLogFile,
    syncLogs,
    onMessage,
    rehydrated,
    setSingleFileMode,
  ]);

  return <RouterProvider router={AppRouter} />;
};
