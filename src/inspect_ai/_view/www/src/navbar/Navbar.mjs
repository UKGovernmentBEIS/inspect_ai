import { html } from "htm/preact";

import { icons, sharedStyles } from "./../Constants.mjs";
import { filename } from "./../utils/Path.mjs";
import { formatPrettyDecimal } from "../utils/Format.mjs";

import { CopyButton } from "./../components/CopyButton.mjs";

export const Navbar = ({
  file,
  task,
  logs,
  model,
  status,
  samples,
  metrics,
  offcanvas,
}) => {
  const toggleOffCanClass = offcanvas ? "" : " d-md-none";
  const logFileName = file ? filename(file) : "";

  let statusPanel;
  if (status === "success") {
    statusPanel = html`<${ResultsPanel} results="${metrics}" />`;
  } else if (status === "cancelled") {
    statusPanel = html`<${CanceledPanel}
      sampleCount=${samples?.length || 0}
    />`;
  } else if (status === "started") {
    statusPanel = html`<${RunningPanel} />`;
  }

  // If no logfile is loaded, just show an empty navbar
  const navbarContents = logFileName
    ? html` <div
          class="navbar-brand navbar-text mb-0"
          style=${{ display: "flex", paddingTop: 0, marginLeft: "0.5rem" }}
        >
          ${logs.files.length > 1 || logs.log_dir
            ? html`<button
                id="sidebarToggle"
                class="btn${toggleOffCanClass}"
                type="button"
                data-bs-toggle="offcanvas"
                data-bs-target="#sidebarOffCanvas"
                aria-controls="sidebarOffCanvas"
                style=${{
                  padding: "0rem 0.1rem 0.1rem 0rem",
                  marginTop: "-8px",
                  marginRight: "0.2rem",
                  lineHeight: "16px",
                }}
              >
                <i class=${icons.menu}></i>
              </button> `
            : ""}
          <div style=${{ display: "flex", flexDirection: "column" }}>
            <div
              style=${{
                marginTop: "0.5rem",
                display: "grid",
                gridTemplateColumns:
                  "minmax(50px,max-content) minmax(100px, max-content)",
              }}
            >
              <div
                style=${{
                  fontWeight: 600,
                  marginRight: "0.3rem",
                  ...sharedStyles.wrapText(),
                }}
                title=${task}
              >
                ${task}
              </div>
              <div
                style=${{
                  fontWeight: 300,
                  fontSize: "0.9em",
                  paddingTop: "0.15em",
                  ...sharedStyles.wrapText(),
                }}
                title=${model}
              >
                ${model}
              </div>
            </div>
            <div
              style=${{
                opacity: "0.7",
                paddingBottom: 0,
                fontSize: "0.7rem",
                display: "grid",
                gridTemplateColumns: "minmax(0,max-content) max-content",
              }}
            >
              <div
                style=${{
                  ...sharedStyles.wrapText(),
                }}
              >
                ${logFileName}
              </div>
              <${CopyButton} value=${file} />
            </div>
          </div>
        </div>

        <div
          class="navbar-text"
          style=${{
            justifyContent: "end",
            marginRight: "1em",
          }}
        >
          ${statusPanel}
        </div>`
    : "";

  return html`
    <nav
      class="navbar sticky-top"
      style=${{
        flexWrap: "nowrap",
        borderBottom: "solid var(--bs-border-color) 1px",
      }}
    >
      <div
        style=${{
          display: "grid",
          gridTemplateColumns: "1fr max-content",
          width: "100%",
        }}
      >
        ${navbarContents}
      </div>
    </nav>
  `;
};

const CanceledPanel = ({ sampleCount }) => {
  return html`<div
    style=${{
      padding: "1em",
      marginTop: "0.5em",
      textTransform: "uppercase",
      fontSize: "0.7em",
    }}
  >
    <i class="${icons.logging.info}" style=${{ fontSize: "1.1em" }} /> cancelled
    (${sampleCount} ${sampleCount === 1 ? "sample" : "samples"})
  </div>`;
};

const RunningPanel = () => {
  return html`<div
    style=${{
      marginTop: "0.5em",
      display: "inline-grid",
      gridTemplateColumns: "auto auto",
    }}
  >
    <div class="spinner-border spinner-border-sm" role="status"></div>
    <div
      style=${{ marginLeft: "0.3em", paddingTop: "0.2em", fontSize: "0.7em" }}
    >
      Running
    </div>
  </div>`;
};

const ResultsPanel = ({ results }) => {
  // Map the scores into a list of key/values
  const metrics = results
    ? Object.keys(results).map((key) => {
        return { name: key, value: results[key].value };
      })
    : [];

  return html`<div
    style=${{
      display: "flex",
      flexDirection: "row",
      flexWrap: "wrap",
      justifyContent: "end",
    }}
  >
    ${metrics.map((metric, i) => {
      return html`<div style=${{ paddingLeft: i === 0 ? "0" : "1em" }}>
        <div
          style=${{
            fontSize: "0.7rem",
            fontWeight: "200",
            textAlign: "center",
            marginBottom: "-0.3rem",
            paddingTop: "0.3rem",
          }}
        >
          ${metric.name}
        </div>
        <div
          style=${{
            fontSize: "1.5rem",
            fontWeight: "500",
            textAlign: "center",
          }}
        >
          ${formatPrettyDecimal(metric.value)}
        </div>
      </div>`;
    })}
  </div>`;
};
