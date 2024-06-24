import { html } from "htm/preact";
import { useCallback, useEffect, useMemo, useState } from "preact/hooks";

// Registration component
import "./src/Register.mjs";

// The api for loading evals
import api from "./src/api/index.mjs";

import { throttle } from "./src/utils/events.mjs";
import { sleep } from "./src/utils/sleep.mjs";

import { AppErrorBoundary } from "./src/components/AppErrorBoundary.mjs";
import { ErrorPanel } from "./src/components/ErrorPanel.mjs";
import { ProgressBar } from "./src/components/ProgressBar.mjs";

import { Navbar } from "./src/navbar/Navbar.mjs";
import { Sidebar } from "./src/sidebar/Sidebar.mjs";
import { WorkSpace } from "./src/workspace/WorkSpace.mjs";

export function App() {
  const [selected, setSelected] = useState(-1);
  const [pendingLog, setPendingLog] = useState(undefined);
  const [logs, setLogs] = useState({ log_dir: "", files: [] });
  const [logHeaders, setLogHeaders] = useState({});
  const [offcanvas, setOffcanvas] = useState(false);
  const [currentLog, setCurrentLog] = useState({
    contents: undefined,
    name: undefined,
    raw: undefined,
  });
  const [status, setStatus] = useState({
    loading: true,
    error: undefined,
  });
  const [headersLoading, setHeadersLoading] = useState(false);

  // Read header information for the logs
  // and then update
  useEffect(async () => {
    // Loeading headers
    setHeadersLoading(true);

    // Group into chunks
    const chunkSize = 12;
    const fileLists = [];
    for (let i = 0; i < logs.files.length; i += chunkSize) {
      let chunk = logs.files.slice(i, i + chunkSize).map((log) => {
        return log.name;
      });
      fileLists.push(chunk);
    }

    // Chunk by chunk, read the header information
    try {
      for (const fileList of fileLists) {
        const headers = await api.eval_log_headers(fileList);
        setLogHeaders((prev) => {
          const updatedHeaders = {};
          headers.forEach((header, index) => {
            const logFile = fileList[index];
            updatedHeaders[logFile] = header;
          });
          return { ...prev, ...updatedHeaders };
        });
        await sleep(2000);
      }
    } catch (e) {
      // Show an error
      console.log(e);
      setStatus({ loading: false, error: e });
    }

    setHeadersLoading(false);
  }, [logs, setStatus, setLogHeaders, setHeadersLoading]);

  // Filter out running logs
  const filteredLogs = useMemo(() => {
    // Filter out running tasks
    const notRunning = Object.keys(logHeaders).filter((key) => {
      return logHeaders[key].status !== "started";
    });

    const files = logs.files.filter((file) => {
      return notRunning.includes(file.name);
    });

    return {
      log_dir: logs.log_dir,
      files: files,
    };
  }, [logHeaders, logs]);

  // Load a specific log
  useEffect(async () => {
    const targetLog = filteredLogs.files[selected];
    if (targetLog && (!currentLog || currentLog.name !== targetLog.name)) {
      try {
        setStatus({ loading: true, error: undefined });
        const logContents = await api.eval_log(targetLog.name, false);
        if (logContents) {
          setCurrentLog({
            contents: logContents,
            name: targetLog.name,
            raw: JSON.stringify(logContents, null, 2),
          });
          setStatus({ loading: false, error: undefined });
        }
      } catch (e) {
        // Show an error
        console.log(e);
        setStatus({ loading: false, error: e });
      }
    }
  }, [selected, filteredLogs, currentLog, setCurrentLog, setStatus]);

  // Keep a queue of loading operations that will be run
  // as needed
  const loadLogsImpl = useCallback(async () => {
    const result = await api.eval_logs();
    if (result) {
      setLogs(result);
    } else {
      setLogs({ log_dir: "", files: [] });
    }
  }, []);

  // Debounce the loadLogs function
  const loadLogs = useCallback(
    throttle(() => {
      loadLogsImpl();
    }, 5000),
    [loadLogsImpl],
  );

  // Select any pending logs if they are loaded
  useEffect(async () => {
    if (pendingLog) {
      const index = filteredLogs.files.findIndex((val) => {
        return pendingLog.endsWith(val.name);
      });
      if (index > -1) {
        setSelected(index);
        setPendingLog(undefined);
      } else {
        if (
          !logs.files.find((val) => {
            return pendingLog.endsWith(val.name);
          })
        ) {
          await loadLogs();
        }
      }
    }
  }, [pendingLog, filteredLogs, setSelected, setPendingLog, loadLogs]);

  const onMessage = useMemo(() => {
    return async (e) => {
      const type = e.data.type || e.data.message;
      switch (type) {
        case "updateState": {
          if (e.data.url) {
            const decodedUrl = decodeURIComponent(e.data.url);
            setPendingLog(decodedUrl);
          }
        }
      }
    };
  }, [setPendingLog]);

  // listen for updateState messages from vscode
  useEffect(() => {
    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
    };
  }, [onMessage]);

  useEffect(async () => {
    // See whether a specific task_file has been passed.
    const urlParams = new URLSearchParams(window.location.search);

    // Note whether we should default off canvas the sidebar
    setOffcanvas(true);

    // If the URL provides a task file, load that
    const logPath = urlParams.get("task_file");
    const load = logPath
      ? async () => {
          setLogs({
            log_dir: "",
            files: [{ name: logPath }],
          });
        }
      : loadLogs;

    // See whether there is state encoding in the document itself
    const embeddedState = document.getElementById("logview-state");
    if (embeddedState) {
      // Sending this message will result in loading occuring
      const state = JSON.parse(embeddedState.textContent);
      onMessage({ data: state });
    } else {
      // initial fetch of logs
      await load();
    }

    // Select the first log if there wasn't some
    // message embedded within the view html itself
    if (selected === -1 && !embeddedState) {
      setSelected(0);
    }

    // poll every 1s for events
    setInterval(() => {
      api.client_events().then(async (events) => {
        if (events.includes("reload")) {
          window.location.reload(true);
        }
        if (events.includes("refresh-evals")) {
          await load();
          setSelected(0);
        }
      });
    }, 1000);
  }, []);

  // Configure an app envelope specific to the current state
  // if there are no log files, then don't show sidebar
  const fullScreen = filteredLogs.files.length === 1 && !filteredLogs.log_dir;

  const appEnvelope = [
    html` <${Navbar}
      file=${currentLog.name}
      logs=${filteredLogs}
      task=${currentLog.contents?.eval?.task}
      model=${currentLog.contents?.eval?.model}
      metrics=${currentLog.contents?.results?.metrics}
      samples=${currentLog.contents?.samples}
      status=${currentLog.contents?.status}
      offcanvas=${offcanvas}
    />`,
  ];
  if (!fullScreen) {
    appEnvelope.push(html`
      <${Sidebar}
        logs=${filteredLogs}
        logHeaders=${logHeaders}
        loading=${headersLoading}
        offcanvas=${offcanvas}
        selectedIndex=${selected}
        onSelectedIndexChanged=${(index) => {
          setSelected(index);

          // hide the sidebar offcanvas
          var myOffcanvas = document.getElementById("sidebarOffCanvas");
          var bsOffcanvas = bootstrap.Offcanvas.getInstance(myOffcanvas);
          if (bsOffcanvas) {
            bsOffcanvas.hide();
          }
        }}
      />
    `);
  }

  const workspace = useMemo(() => {
    if (status.error) {
      return html`<${ErrorPanel}
        title="An error occurred while loading this task."
        error=${status.error}
      />`;
    } else {
      return html` <${WorkSpace}
        logs=${filteredLogs}
        log=${currentLog}
        selected=${selected}
        fullScreen=${fullScreen}
        offcanvas=${offcanvas}
      />`;
    }
  }, [logs, currentLog, selected, fullScreen, offcanvas, status]);

  return html`
    <${AppErrorBoundary}>
    <div>
      ${appEnvelope}
      <${ProgressBar} animating=${status.loading} />
      ${workspace}
    </div>
    </${AppErrorBoundary}>
  `;
}
