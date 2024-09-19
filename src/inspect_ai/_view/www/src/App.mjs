import "bootstrap/dist/css/bootstrap.css";
import "bootstrap-icons/font/bootstrap-icons.css";
import "prismjs/themes/prism.css";
import "prismjs";
import "../App.css";

import { default as ClipboardJS } from "clipboard";
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

export function App({ api, pollForLogs = true }) {
  const [selected, setSelected] = useState(-1);
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
  const [capabilities, setCapabilities] = useState({
    downloadFiles: true,
    webWorkers: true,
  });
  const [showFind, setShowFind] = useState(false);
  const mainAppRef = useRef();

  // Read header information for the logs
  // and then update
  useEffect(async () => {
    // Loading headers
    setHeadersLoading(true);

    // Group into chunks
    const chunkSize = 8;
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
        if (headers.length === chunkSize) {
          await sleep(5000);
        }
      }
    } catch (e) {
      // Show an error
      console.log(e);
      setStatus({ loading: false, error: e });
    }

    setHeadersLoading(false);
  }, [logs, setStatus, setLogHeaders, setHeadersLoading]);

  // Load a specific log
  useEffect(async () => {
    const targetLog = logs.files[selected];
    if (targetLog && (!currentLog || currentLog.name !== targetLog.name)) {
      try {
        setStatus({ loading: true, error: undefined });
        const logContents = await loadLog(targetLog.name);
        if (logContents) {
          const log = logContents.parsed;
          setCurrentLog({
            contents: log,
            name: targetLog.name,
            raw: logContents.raw,
          });
          setStatus({ loading: false, error: undefined });
        }
      } catch (e) {
        // Show an error
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
  }, [selected, logs, capabilities, currentLog, setCurrentLog, setStatus]);

  // Load the list of logs
  const loadLogs = async () => {
    try {
      const result = await api.eval_logs();
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
      const logContents = await api.eval_log(logFileName, 100, capabilities);
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
      const targetLog = logs.files[selected];
      const logContents = await loadLog(targetLog.name);
      if (logContents) {
        const log = logContents.parsed;
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

        setCurrentLog({
          contents: log,
          name: targetLog.name,
          raw: logContents.raw,
        });
        setStatus({ loading: false, error: undefined });
      }
    } catch (e) {
      // Show an error
      console.log(e);
      setStatus({ loading: false, error: e });
    }
  }, [logs, selected, setStatus, setCurrentLog, setLogHeaders]);

  const showLogFile = useCallback(
    async (logUrl) => {
      const index = logs.files.findIndex((val) => {
        return logUrl.endsWith(val.name);
      });
      if (index > -1) {
        setSelected(index);
      } else {
        const result = await loadLogs();
        const idx = result.files.findIndex((file) => {
          return logUrl.endsWith(file.name);
        });
        setLogs(result);
        setSelected(idx > -1 ? idx : 0);
      }
    },
    [logs, setSelected, setLogs],
  );

  const refreshLogList = useCallback(async () => {
    const currentLog = logs.files[selected > -1 ? selected : 0];

    const refreshedLogs = await loadLogs();
    const newIndex = refreshedLogs.files.findIndex((file) => {
      return currentLog.name.endsWith(file.name);
    });
    setLogs(refreshedLogs);
    setSelected(newIndex);
  }, [logs, selected, setSelected, setLogs]);

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

  useEffect(async () => {
    // See whether a specific task_file has been passed.
    const urlParams = new URLSearchParams(window.location.search);

    // Determine the capabilities
    // If this is vscode, check for the version meta
    // so we know it supports downloads
    const extensionVersionEl = document.querySelector(
      'meta[name="inspect-extension:version"]',
    );
    const extensionVersion = extensionVersionEl
      ? extensionVersionEl.getAttribute("content")
      : undefined;
    if (isVscode()) {
      if (!extensionVersion) {
        // VSCode hosts before the extension version was communicated don't support
        // downloading or web workers.
        setCapabilities({ downloadFiles: false, webWorkers: false });
      }
    }

    // Note whether we should default off canvas the sidebar
    setOffcanvas(true);

    // If the URL provides a task file, load that
    const logPath = urlParams.get("task_file");

    // Replace any spaces in the path with a '+' sign:
    const resolvedLogPath = logPath ? logPath.replace(" ", "+") : logPath;
    const load = resolvedLogPath
      ? async () => {
          return {
            log_dir: "",
            files: [{ name: resolvedLogPath }],
          };
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
      const result = await load();
      setLogs(result);

      // If a log file was passed, select it
      const log_file = urlParams.get("log_file");
      if (log_file) {
        const index = result.files.findIndex((val) => {
          return log_file.endsWith(val.name);
        });
        if (index > -1) {
          setSelected(index);
        }
      } else if (selected === -1) {
        // Select the first log if there wasn't some
        // message embedded within the view html itself
        setSelected(0);
      }
    }

    new ClipboardJS(".clipboard-button,.copy-button");

    // poll every 1s for events
    if (pollForLogs) {
      setInterval(() => {
        api.client_events().then(async (events) => {
          if (events.includes("reload")) {
            window.location.reload(true);
          }
          if (events.includes("refresh-evals")) {
            const logs = await load();
            setLogs(logs);
            setSelected(0);
          }
        });
      }, 1000);
    }
  }, []);

  // Configure an app envelope specific to the current state
  // if there are no log files, then don't show sidebar
  const fullScreen = logs.files.length === 1 && !logs.log_dir;
  const sidebar =
    !fullScreen && currentLog.contents
      ? html`
          <${Sidebar}
            logs=${logs}
            logHeaders=${logHeaders}
            loading=${headersLoading}
            offcanvas=${offcanvas}
            selectedIndex=${selected}
            onSelectedIndexChanged=${(index) => {
              setSelected(index);

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

  const workspace = useMemo(() => {
    if (status.error) {
      return html`<${ErrorPanel}
        title="An error occurred while loading this task."
        error=${status.error}
      />`;
    } else {
      return html` <${WorkSpace}
        logs=${logs}
        log=${currentLog}
        selected=${selected}
        fullScreen=${fullScreen}
        offcanvas=${offcanvas}
        capabilities=${capabilities}
        showFind=${showFind}
        setShowFind=${setShowFind}
        refreshLog=${refreshLog}
      />`;
    }
  }, [logs, currentLog, selected, fullScreen, offcanvas, status]);

  const fullScreenClz = fullScreen ? " full-screen" : "";
  const offcanvasClz = offcanvas ? " off-canvas" : "";

  const hideFind = useCallback(() => {
    clearDocumentSelection();
    if (showFind) {
      setShowFind(false);
    }
  }, [showFind, setShowFind]);

  return html`
    <${AppErrorBoundary}>
    ${sidebar}
    <div ref=${mainAppRef} class="app-main-grid${fullScreenClz}${offcanvasClz}" tabIndex="0" onKeyDown=${(
      e,
    ) => {
      // regular browsers user their own find
      if (!window.acquireVsCodeApi) {
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
      ${workspace}
    </div>
    </${AppErrorBoundary}>
  `;
}
