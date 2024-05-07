import { html } from "htm/preact";
import { useCallback, useState, useEffect } from "preact/hooks";

import { formatPrettyDecimal } from "./src/utils/Format.mjs";


import "./src/Register.mjs";

import { icons } from "./src/Constants.mjs";
import { WorkSpace } from "./src/workspace/WorkSpace.mjs";
import api from "./src/api/index.mjs";
import { CopyButton } from "./src/components/CopyButton.mjs";

const logFileName = (path) => {
  return path.replace("\\", "/").split('/').pop();
};

export function App() {
  const [selected, setSelected] = useState(0);
  const [logs, setLogs] = useState({ log_dir: "", files: [] });
  const [logHeaders, setLogHeaders] = useState({});
  const [offcanvas, setOffcanvas] = useState(false);

  // reset selection when logs are refreshed
  useEffect(() => {
    // Default select the first item
    let index = 0;
    setSelected(index);
  }, [logs]);

  useEffect(async () => {
    // Read header information for the logs
    // and then update

    // Group into chunks
    const chunkSize = 5;
    const fileLists = [];
    for (let i = 0; i < logs.files.length; i += chunkSize) {
      let chunk = logs.files.slice(i, i + chunkSize).map((log) => { return log.name; });
      fileLists.push(chunk);
    }

    for (const fileList of fileLists) {
      const headers = await api.eval_log_headers(fileList);
      const updatedHeaders = logHeaders;
      headers.forEach((header, index) => {
        const logFile = fileList[index];
        updatedHeaders[logFile] = header;
      })
      setLogHeaders({ ...updatedHeaders });  
    }
  }, [logs]);

  const updateLogs = useCallback(async (log) => {
    // Set the list of logs
    const logresult = await api.eval_logs();
    if (logresult) {
      setLogs(logresult);
      if (log) {
        const name = logFileName(log);
        const index = logresult.files.findIndex((val) => {
          return val.name.endsWith(name);
        })
        setSelected(index);
      }
    } else {
      setLogs({ log_dir: "", files: [] });
    }
  }, [setLogs, setSelected]);

  // listen for updateState messages from vscode
  useEffect(() => {

    const onMessage = (e) => {
      switch (e.data.type || e.data.message) {

        case "updateState": {
          if (e.data.url) {
            updateLogs(e.data.url);
          }
        }
      }
    }

    window.addEventListener("message", onMessage);

    return () => {
      window.removeEventListener("message", onMessage);
    }

  }, [updateLogs]);

  useEffect(async () => {
    const urlParams = new URLSearchParams(window.location.search);

    // Note whether we should default off canvas the sidebar
    setOffcanvas(true);

    // If the URL provides a task file, load that
    const logPath = urlParams.get("task_file");
    const loadLogs = logPath
      ? async () => {
        setLogs({
          log_dir: "",
          files: [{ name: logPath }],
        });
      }
      : updateLogs;

    // initial fetch of logs
    await loadLogs();

    // poll every 1s for events
    setInterval(() => {
      api.client_events().then((events) => {
        if (events.includes("reload")) {
          window.location.reload(true);
        }
        if (events.includes("refresh-evals")) {
          loadLogs();
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
        <${Header} logs=${logs} selected=${selected} offcanvas=${offcanvas} />
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
  return html`
    <div>
      ${appEnvelope}
      <${WorkSpace}
        logs=${logs}
        selected=${selected}
        fullScreen=${fullScreen}
        offcanvas=${offcanvas}
      />
    </div>
  `;
}

const Header = (props) => {
  const toggleOffCanClass = props.offcanvas ? "" : " d-md-none";
  const gearOffCanClass = props.offcanvas ? "" : " d-md-inline";

  const logFiles = props.logs.files || [];
  const logSelected = props.selected || 0;
  const logUri = logFiles.length > logSelected ? logFiles[logSelected].name : "";
  const logName = logFileName(logUri);

  return html`
    <nav class="navbar sticky-top shadow-sm" style=${{ flexWrap: "nowrap" }}>
      <div class="container-fluid">
        <span
          class="navbar-brand mb-0"
          style=${{ display: "flex", alignItems: "center" }}
        >
          <button
            id="sidebarToggle"
            class="btn${toggleOffCanClass}"
            type="button"
            data-bs-toggle="offcanvas"
            data-bs-target="#sidebarOffCanvas"
            aria-controls="sidebarOffCanvas"
            style=${{
      padding: "0rem 0.1rem 0.1rem 0rem",
      marginTop: ".1rem",
      marginRight: "0.2rem",
      lineHeight: "16px",
    }}
          >
            <i class=${icons.menu}></i>
          </button>
          <i
            class="${icons.inspect} d-none ${gearOffCanClass}"
            style=${{ marginRight: "0.3rem" }}
          ></i>
          <span> Inspect View </span>
        </span>
        <div
          class="navbar-text"
          style=${{
      paddingTop: "0.3rem",
      paddingBottom: 0,
      fontSize: "0.8rem",
      whiteSpace: "nowrap",
      textOverflow: "ellipsis",
      overflow: "hidden",
    }}
        >
          ${logName}<${CopyButton} value=${logUri}/>
        </div>
      </div>
    </nav>
  `;
};

const Sidebar = (props) => {
  const btnOffCanClass = props.offcanvas ? "" : " d-md-none";
  const sidebarOffCanClass = props.offcanvas ? " offcanvas" : " offcanvas-md";
  const logHeaders = props.logHeaders;

  return html`
    <div
      class="sidebar border-end offcanvas-start${sidebarOffCanClass}"
      id="sidebarOffCanvas"
    >
      <div
        style=${{
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
    }}
      >
        <span
          style=${{
      paddingLeft: "0.5rem",
      fontWeight: "500",
      fontSize: "1.1rem",
      opacity: "0.7",
    }}
          >${props.offcanvas ? "Log History" : ""}</span
        >
        <button
          id="sidebarToggle"
          class="btn d-inline${btnOffCanClass}"
          type="button"
          data-bs-toggle="offcanvas"
          data-bs-target="#sidebarOffCanvas"
          aria-controls="sidebarOffCanvas"
          style=${{ padding: ".1rem", alignSelf: "end", width: "40px" }}
        >
          <i class=${icons.close}></i>
        </button>
      </div>
      <ul class="list-group">
        ${props.logs.files.map((file, index) => {
      const active = index === props.selected ? " active" : "";
      const time = new Date(file.mtime);
      const logHeader = logHeaders[file.name];
      const hyperparameters = logHeader ? {
        ...logHeader.plan?.config,
        ...logHeader.eval?.task_args,
      } : undefined;

      const model = logHeader?.eval?.model;
      const dataset = logHeader?.eval?.dataset;
      const scorer = logHeader?.results?.scorer?.name;

      return html`
            <li
              class="list-group-item list-group-item-action${active}"
              onclick=${() => props.onSelected(index)}
              style=${{ fontSize: "0.8rem" }}
            >
              <div
                style=${{
          display: "flex",
          flexDirection: "row",
          justifyContent: "space-between",
        }}
              >
                <div style=${{overflow: "hidden"}}>
                  <div
                    style=${{
                      fontSize: "1.5em",
                      fontWeight: "600",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis"
                    }}
                  >
                    ${logHeader?.eval?.task || file.task}
                  </div>
                  <small class="mb-1 text-muted">
                    ${time.toDateString()}
                    ${time.toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        })}
                  </small>

                  ${model ? html` <div><small class="mb-1 text-muted">${model}</small></div>` : ""}
                </div>
                ${logHeader?.results?.metrics
          ? html`<div style=${{ display: "flex", flexDirection: "row", flexWrap: "wrap", justifyContent: "flex-end" }}>
                          
                      ${Object.keys(logHeader?.results.metrics).map(
            (metric) => {
              return html`
                            <div
                              style=${{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  marginLeft: "1em"
                }}
                            >
                              <div
                                style=${{ fontWeight: 300 }}
                              >
                                ${logHeader?.results.metrics[metric].name}
                                </div>
                              <div style=${{ fontWeight: 600, fontSize: "1.5em" }}>
                                ${formatPrettyDecimal(
                  logHeader?.results.metrics[metric].value
                )}
                              </div>
                            </div>
                          `;
            }
          )}
                    </div>`
          : logHeader?.status === "error" ? html`<div style=${{ color: "var(--bs-danger)" }}>Eval Error</div>` : ""}
              </div>
              <div style=${{ marginTop: "0.4em" }}>
              <small class="mb-1 text-muted">
              ${hyperparameters ? Object.keys((hyperparameters)).map((key) => {
            return `${key}: ${hyperparameters[key]}`
          }).join(", ") : ""
        } 
              </small>
              </div>
              ${dataset || scorer ? html`<div style=${{ display: "flex", justifyContent: "space-between", marginTop: "0.5em" }}><span>dataset: ${dataset.name || "(samples)"}</span><span>scorer: ${scorer}</span></div>` : ""}

            </li>
          `;
    })}
      </ul>
    </div>
  `;
};
