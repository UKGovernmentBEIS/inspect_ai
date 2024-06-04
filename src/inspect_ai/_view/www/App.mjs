import { html } from "htm/preact";
import { useCallback, useState, useEffect, useRef } from "preact/hooks";

// Registration component
import "./src/Register.mjs";

// The api for loading evals
import api from "./src/api/index.mjs";

import { filename } from "./src/utils/Path.mjs"
import { sleep } from "./src/utils/sleep.mjs"

import { AppErrorBoundary } from "./src/components/AppErrorBoundary.mjs"
import { ErrorPanel } from "./src/components/ErrorPanel.mjs";
import { LoadingScreen } from "./src/components/LoadingScreen.mjs";

import { Navbar } from "./src/navbar/Navbar.mjs"
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
    raw: undefined
  });
  const [status, setStatus] = useState({
    loading: true,
    error: undefined
  });


  // Read header information for the logs
  // and then update
  useEffect(async () => {
    // Group into chunks
    const chunkSize = 12;
    const fileLists = [];
    for (let i = 0; i < logs.files.length; i += chunkSize) {
      let chunk = logs.files.slice(i, i + chunkSize).map((log) => {
        return log.name;
      }).filter((chunk) => {
        // Don't reload headers that we already have status for
        // TODO: We should re-compute the next chunk as needed
        // TODO: If we stream or refresh logs, we need to be smarter
        // about refreshing this
        const currentHeader = logHeaders[chunk];
        if (currentHeader) {
          return false;
        } else {
          return true;
        }
      });
      fileLists.push(chunk);
    }

    // Chunk by chunk, read the header information
    for (const fileList of fileLists) {
      const headers = await api.eval_log_headers(fileList);
      const updatedHeaders = logHeaders;
      headers.forEach((header, index) => {
        const logFile = fileList[index];
        updatedHeaders[logFile] = header;
      });
      setLogHeaders({ ...logHeaders, ...updatedHeaders });
      await sleep(2000);
    }
  }, [logs]);

  // Load a specific log file
  useEffect(async () => {
    if (logs.files.length > 0 && selected > -1) {
      const targetLog = logs.files[selected];
      const header = logHeaders[targetLog.name];
      // Only show the log once we have at least one log which isn't currently running.
      // This prevents a 'flash', for example, the most recent log is running and would be selected
      if (currentLog.name !== targetLog.name && header && header.status !== "started") {
        try {
          setStatus({ loading: true, error: undefined });
          const logContents = await api.eval_log(targetLog.name, false);
          if (logContents) {
            setCurrentLog({ contents: logContents, name: targetLog.name, raw: JSON.stringify(logContents, null, 2) });
            setStatus({ loading: false, error: undefined });
          }
        } catch (e) {
          // Show an error
          console.log(e);
          setStatus({ loading: false, error: e });
        }
      }
    } else {
      setCurrentLog({ contents: undefined, name: undefined, raw: undefined });
    }
  }, [selected, logs, logHeaders]);

  useEffect(() => {
    // Filter out running tasks
    const currentlogs = logs;
    const runningEvals = Object.keys(logHeaders).filter((key) => {
      return logHeaders[key].status === "started";
    });

    const nonRunningLogFiles = currentlogs.files.filter((file) => {
      return !runningEvals.includes(file.name)
    });

    if (nonRunningLogFiles.length !== currentlogs.files.length) {
      setLogs({ log_dir: currentlogs.log_dir, files: nonRunningLogFiles });
    }

  }, [logHeaders]);

  // Keep a queue of loading operations that will be run
  // as needed
  const loadQueue = useRef(Promise.resolve());
  const loadLogs = useCallback(async () => {

    // Chain the new load operation onto the current queue
    loadQueue.current = loadQueue.current
      .then(async () => {

        // first check whether the selected file has already
        // been loaded, and if so, just selected it without
        // reloading
        if (logs.files.length > 0 && currentLog.name) {
          const name = filename(currentLog.name);
          if (logs.files.includes(name)) {
            return;
          }
        }

        // Since the log file isn't in the list, we'll need to 
        // load or re-load logs files
        const result = await api.eval_logs();

        if (result) {
          setLogs(result);
        } else {
          setLogs({ log_dir: "", files: [] });
        }
      })
      .catch((err) => {
        // Handle errors here if needed
        console.error(err);
      });

    // Wait for the current operation to finish
    await loadQueue.current;
  }, [setLogs, currentLog]);


  // Ensure that we have a selected index when there is are 
  // new logs
  useEffect(() => {
    if (logs && pendingLog) {
      const index = logs.files.findIndex((val) => {
        return pendingLog.endsWith(val.name);
      });
      if (index > -1) {
        setSelected(index);    
      }
      setPendingLog(undefined);
    }
  }, [logs, pendingLog])

  // listen for updateState messages from vscode
  useEffect(() => {
    const onMessage = async (e) => {
      switch (e.data.type || e.data.message) {
        case "updateState": {
          if (e.data.url) {
            const index = logs.files.findIndex((val) => {
              return e.data.url.endsWith(val.name);
            });
            if (index > -1) {
              // Select the correct index
              setSelected(index);
            } else {
              await loadLogs();
              setPendingLog(e.data.url);
            }
          }
        }
      }
    };
    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
    };
  }, [logs, setCurrentLog, setPendingLog]);

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

    // initial fetch of logs
    await load();

    // Select the first log
    if (selected === -1) {
      setSelected(0);
    }

    // poll every 1s for events
    setInterval(() => {
      api.client_events().then((events) => {
        if (events.includes("reload")) {
          window.location.reload(true);
        }
        if (events.includes("refresh-evals")) {
          load();
        }
      });
    }, 1000);
  }, []);

  // Configure an app envelope specific to the current state
  // if there are no log files, then don't show sidebar
  const fullScreen = logs.files.length === 1 && !logs.log_dir;

  const appEnvelope = fullScreen
    ? ""
    : html`
        <${Navbar} 
          file=${currentLog.name}
          task=${currentLog.contents?.eval?.task}
          model=${currentLog.contents?.eval?.model}
          metrics=${currentLog.contents?.results?.metrics}
          samples=${currentLog.contents?.samples}
          status=${currentLog.contents?.status}
          offcanvas=${offcanvas} />
        <${Sidebar}
          logs=${logs}
          logHeaders=${logHeaders}
          offcanvas=${offcanvas}
          selected=${selected}
          onSelected=${(index) => {
        setSelected(index);

        // hide the sidebar offcanvas
        var myOffcanvas = document.getElementById("sidebarOffCanvas");
        var bsOffcanvas = bootstrap.Offcanvas.getInstance(myOffcanvas);
        if (bsOffcanvas) {
          bsOffcanvas.hide();
        }
      }}
        />
      `;

  const progress = () => {
    if (status.loading) {
      return html`<${LoadingScreen} />`;
    }
  }

  const workspace = () => {
    if (status.error) {
      return html`<${ErrorPanel}
        title="An error occurred while loading this task."
        error=${status.error}
      />`;
    } else {
      return html`
      <${WorkSpace}
        logs=${logs}
        log=${currentLog}
        selected=${selected}
        fullScreen=${fullScreen}
        offcanvas=${offcanvas}
      />`
    }
  }
  return html`
    <${AppErrorBoundary}>
    <div>
      ${appEnvelope}
      ${progress()}
      ${workspace()}
    </div>
    </${AppErrorBoundary}>
  `;
}
