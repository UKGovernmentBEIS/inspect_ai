import { html } from "htm/preact";

import { icons } from "./../Constants.mjs";
import { formatPrettyDecimal } from "./../utils/Format.mjs";
import { ProgressBar } from "../components/ProgressBar.mjs";

export const Sidebar = ({
  offcanvas,
  logs,
  loading,
  logHeaders,
  selectedIndex,
  onSelectedIndexChanged,
}) => {
  const btnOffCanClass = offcanvas ? "" : " d-md-none";
  const sidebarOffCanClass = offcanvas ? " offcanvas" : " offcanvas-md";

  return html`
    <div
      class="sidebar border-end offcanvas-start${sidebarOffCanClass}"
      id="sidebarOffCanvas"
      style=${{ display: "flex", flexDirection: "column", height: "100%" }}
    >
      <div
        style=${{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) auto",
          columnGap: "0.2rem",
          alignItems: "center",
          paddingLeft: "0.5rem",
          opacity: "0.7",
          position: "fixed",
          width: "var(--sidebar-width)",
          zIndex: 10,
          borderBottom: "solid var(--bs-light-border-subtle) 1px",
        }}
      >
        <${LogDirectoryTitle} log_dir=${logs.log_dir} offcanvas=${offcanvas} />
        <button
          id="sidebarToggle"
          class="btn d-inline${btnOffCanClass}"
          type="button"
          data-bs-toggle="offcanvas"
          data-bs-target="#sidebarOffCanvas"
          aria-controls="sidebarOffCanvas"
          style=${{
            padding: ".1rem",
            alignSelf: "end",
            width: "40px",
            flex: "0 0 content",
          }}
        >
          <i class=${icons.close}></i>
        </button>
      </div>
      <div style=${{ marginTop: "43px" }}>
        <${ProgressBar} animating=${loading} style=${{ marginTop: "-2px" }} />
      </div>
      <ul class="list-group" style=${{ flexGrow: 1, overflowY: "auto" }}>
        ${logs.files.map((file, index) => {
          const active = index === selectedIndex ? " active" : "";
          const logHeader = logHeaders[file.name];
          const hyperparameters = logHeader
            ? {
                ...logHeader.plan?.config,
                ...logHeader.eval?.task_args,
              }
            : undefined;

          const model = logHeader?.eval?.model;
          const dataset = logHeader?.eval?.dataset;
          const scorer = logHeader?.results?.scorer?.name;

          const completed = logHeader?.stats?.completed_at;
          const time = completed ? new Date(completed) : undefined;
          const timeStr = time
            ? `${time.toDateString()}
          ${time.toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}`
            : "";

          return html`
            <li
              class="list-group-item list-group-item-action${active}"
              onclick=${() => onSelectedIndexChanged(index)}
              style=${{ fontSize: "0.8rem" }}
            >
              <div
                style=${{
                  display: "flex",
                  flexDirection: "row",
                  justifyContent: "space-between",
                }}
              >
                <div style=${{ overflow: "hidden" }}>
                  <div
                    style=${{
                      fontSize: "1.5em",
                      fontWeight: "600",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    ${logHeader?.eval?.task || file.task}
                  </div>
                  <small class="mb-1 text-muted"> ${timeStr} </small>

                  ${model
                    ? html` <div>
                        <small class="mb-1 text-muted">${model}</small>
                      </div>`
                    : ""}
                </div>
                ${logHeader?.results?.metrics
                  ? html`<div
                      style=${{
                        display: "flex",
                        flexDirection: "row",
                        flexWrap: "wrap",
                        justifyContent: "flex-end",
                      }}
                    >
                      ${Object.keys(logHeader?.results.metrics).map(
                        (metric) => {
                          return html`
                            <div
                              style=${{
                                display: "flex",
                                flexDirection: "column",
                                alignItems: "center",
                                marginLeft: "1em",
                              }}
                            >
                              <div style=${{ fontWeight: 300 }}>
                                ${logHeader?.results.metrics[metric].name}
                              </div>
                              <div
                                style=${{ fontWeight: 600, fontSize: "1.5em" }}
                              >
                                ${formatPrettyDecimal(
                                  logHeader?.results.metrics[metric].value,
                                )}
                              </div>
                            </div>
                          `;
                        },
                      )}
                    </div>`
                  : logHeader?.status === "error"
                    ? html`<div style=${{ color: "var(--bs-danger)" }}>
                        Eval Error
                      </div>`
                    : logHeader?.status === "cancelled"
                      ? html`<div style=${{ color: "var(--bs-secondary)" }}>
                          Cancelled
                        </div>`
                      : logHeader?.status === "started"
                        ? html`<div
                            class="spinner-border spinner-border-sm"
                            role="status"
                          >
                            <span class="visually-hidden">Loading...</span>
                          </div>`
                        : ""}
              </div>
              <div style=${{ marginTop: "0.4em" }}>
                <small class="mb-1 text-muted">
                  ${hyperparameters
                    ? Object.keys(hyperparameters)
                        .map((key) => {
                          return `${key}: ${hyperparameters[key]}`;
                        })
                        .join(", ")
                    : ""}
                </small>
              </div>
              ${(dataset || scorer) && logHeader?.status === "success"
                ? html`<div
                    style=${{
                      display: "flex",
                      justifyContent: "space-between",
                      marginTop: "0.5em",
                    }}
                  >
                    <span>dataset: ${dataset.name || "(samples)"}</span
                    ><span>scorer: ${scorer}</span>
                  </div>`
                : ""}
            </li>
          `;
        })}
      </ul>
    </div>
  `;
};

const prettyDir = (path) => {
  try {
    // Try to create a new URL object
    let url = new URL(path);

    if (url.protocol === "file:") {
      return url.pathname;
    } else {
      return path;
    }
  } catch {
    return path;
  }
};

const LogDirectoryTitle = ({ log_dir, offcanvas }) => {
  if (log_dir) {
    const displayDir = prettyDir(log_dir);
    return html`<div style=${{ display: "flex", flexDirection: "column" }}>
      <span style=${{ fontSize: "0.5rem", textTransform: "uppercase" }}
        >Log Directory</span
      >
      <span
        title=${displayDir}
        style=${{
          fontWeight: "400",
          fontSize: "0.7rem",
          overflow: "hidden",
          whiteSpace: "nowrap",
          textOverflow: "ellipsis",
        }}
        >${offcanvas ? displayDir : ""}</span
      >
    </div>`;
  } else {
    return html`<span
      style=${{
        fontWeight: "500",
        fontSize: "1.5rem",
      }}
      >${offcanvas ? "Log History" : ""}
    </span>`;
  }
};
