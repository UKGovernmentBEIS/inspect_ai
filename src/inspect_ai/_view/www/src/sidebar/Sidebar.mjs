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
      <div style=${{ marginTop: "41px", zIndex: 3 }}>
        <${ProgressBar} animating=${loading} />
      </div>
      <ul
        class="list-group"
        style=${{ flexGrow: 1, overflowY: "auto", marginTop: "-3px" }}
      >
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

          const uniqScorers = new Set();
          logHeader?.results?.scores?.forEach((scorer) => {
            uniqScorers.add(scorer.name);
          });
          const scorer = Array.from(uniqScorers).join(",");

          const scorerLabel =
            Object.keys(logHeader?.results?.scores || {}).length === 1
              ? "scorer"
              : "scorers";

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
                <${EvalStatus} logHeader=${logHeader} />
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
                    ><span>${scorerLabel}: ${scorer}</span>
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

const EvalStatus = ({ logHeader }) => {
  switch (logHeader.status) {
    case "error":
      return html`<${StatusError} message="Error" />`;

    case "cancelled":
      return html`<${StatusCancelled} message="Cancelled" />`;

    case "started":
      return html`<${StatusRunning} message="Running" />`;

    default:
      if (logHeader?.results?.scores && logHeader.results.scores.length > 0) {
        if (logHeader.results.scores.length === 1) {
          return html`<${SidebarScore}
            scorer=${logHeader.results.scores[0]}
          />`;
        } else {
          return html`<${SidebarScores} scores=${logHeader.results.scores} />`;
        }
      } else {
        return "";
      }
  }
};

const SidebarScore = ({ scorer }) => {
  return html`<div
    style=${{
      display: "flex",
      flexDirection: "row",
      flexWrap: "wrap",
      justifyContent: "flex-end",
    }}
  >
    ${Object.keys(scorer.metrics).map((metric) => {
      return html`
        <div
          style=${{
            display: "flex",
            flexDirection: "column",
            alignItems: "flex-end",
            marginLeft: "1em",
            marginBottom: "0.4em",
          }}
        >
          <div
            style=${{
              fontWeight: 300,
              marginBottom: "-0.3em",
            }}
          >
            ${scorer.metrics[metric].name}
          </div>
          ${scorer.reducer
            ? html`<div
                style=${{
                  fontWeight: 300,
                  fontSize: "0.9em",
                  marginBottom: "-0.2rem",
                }}
              >
                ${scorer.reducer}
              </div>`
            : ""}
          <div style=${{ fontWeight: 600, fontSize: "1.5em" }}>
            ${formatPrettyDecimal(scorer.metrics[metric].value)}
          </div>
        </div>
      `;
    })}
  </div>`;
};

const SidebarScores = ({ scores }) => {
  return html`<div
    style=${{
      display: "flex",
      flexDirection: "row",
      flexWrap: "wrap",
      justifyContent: "flex-end",
      rowGap: "1em",
    }}
  >
    ${scores.map((score) => {
      const name = score.name;
      const reducer = score.reducer;
      return html`
        <div
          style=${{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            marginLeft: "1em",
          }}
        >
          <div
            style=${{
              fontSize: "0.6rem",
              width: "100%",
              fontWeight: 300,
              borderBottom: "solid var(--bs-border-color) 1px",
              textTransform: "uppercase",
            }}
          >
            ${name}
          </div>
          ${reducer
            ? html` <div
                style=${{
                  fontSize: "0.6rem",
                  width: "100%",
                  fontWeight: 300,
                }}
              >
                ${reducer}
              </div>`
            : ""}
          <div
            style=${{
              fontSize: "0.7rem",
              display: "grid",
              gridTemplateColumns: "max-content max-content",
              gridGap: "0 0.3rem",
            }}
          >
            ${Object.keys(score.metrics).map((key) => {
              const metric = score.metrics[key];
              return html` <div>${metric.name}</div>
                <div style=${{ fontWeight: "600" }}>
                  ${formatPrettyDecimal(metric.value)}
                </div>`;
            })}
          </div>
        </div>
      `;
    })}
  </div>`;
};

const StatusCancelled = ({ message }) => {
  return html`<div style=${{ color: "var(--bs-secondary)" }}>${message}</div>`;
};

const StatusRunning = ({ message }) => {
  return html`<div class="spinner-border spinner-border-sm" role="status">
    <span class="visually-hidden">${message}</span>
  </div>`;
};

const StatusError = ({ message }) => {
  return html`<div style=${{ color: "var(--bs-danger)" }}>${message}</div>`;
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
