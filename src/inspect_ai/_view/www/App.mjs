import { html } from "htm/preact";
import { useState, useEffect } from "preact/hooks";

import { formatPrettyDecimal } from "./src/utils/Format.mjs";

import { client_events, eval_logs } from "api";

import "./src/Register.mjs";

import { icons } from "./src/Constants.mjs";
import { WorkSpace } from "./src/workspace/WorkSpace.mjs";
import { eval_log } from "./api.mjs";

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

  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);

    // Note whether we should default off canvas the sidebar
    setOffcanvas(true);

    // If the URL provides a task file, load that
    const logPath = urlParams.get("task_file");
    const loadLogs = logPath
      ? () => {
          setLogs({
            log_dir: "",
            files: [{ name: logPath }],
          });
        }
      : () => {
          eval_logs().then((logresult) => {
            // Set the list of logs
            setLogs(logresult);

            // Read header information for the logs
            // and then update
            const updatedHeaders = logHeaders;
            Promise.all(
              logresult.files.map(async (file) => {
                try { 
                  const result = await eval_log(file.name, true);
                  return { file: file.name, result };
                } catch { }
              })
            ).then((headerResults) => {
              for (const headerResult of headerResults) {
                if (headerResult) {
                  updatedHeaders[headerResult.file] = headerResult.result;
                }
              }
              setLogHeaders({ ...updatedHeaders });
            });
          });
        };

    // initial fetch of logs
    loadLogs();

    // poll every 1s for events
    setInterval(() => {
      client_events().then((events) => {
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
        <${Header} logs=${logs} offcanvas=${offcanvas} />
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
        <span
          class="navbar-text"
          style=${{
            paddingTop: "0.3rem",
            paddingBottom: 0,
            fontSize: "1rem",
            whiteSpace: "nowrap",
            textOverflow: "ellipsis",
            overflow: "hidden",
          }}
        >
          ${props.logs.log_dir}
        </span>
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
                <div>
                  <div
                    style=${{
                      fontSize: "1.4em",
                      fontWeight: "600",
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

                  ${logHeader?.eval?.model
                    ? html` <div>
                        <small> ${logHeader?.eval.model} </small>
                      </div>`
                    : ""}
                </div>
                ${logHeader?.results?.metrics
                  ? html`<div style=${{display: "flex", flexDirection: "row", flexWrap: "wrap", justifyContent: "flex-end" }}>
                          
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
                              <div style=${{fontWeight: 600, fontSize: "1.4em"}}>
                                ${formatPrettyDecimal(
                                  logHeader?.results.metrics[metric].value
                                )}
                              </div>
                            </div>
                          `;
                        }
                      )}
                    </div>`
                  : logHeader?.status === "error" ? html`<div style=${{color: "var(--bs-danger)"}}>Eval Error</div>` : ""}
              </div>
              <small style=${{ marginTop: "0.4em" }}>
              ${
                hyperparameters ? Object.keys((hyperparameters)).map((key) => {
                  return `${key}: ${hyperparameters[key]}`
                }).join(", ") : ""
              } 
              </small>
            </li>
          `;
        })}
      </ul>
    </div>
  `;
};
