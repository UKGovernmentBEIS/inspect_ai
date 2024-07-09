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
  results,
  offcanvas,
}) => {
  const toggleOffCanClass = offcanvas ? "" : " d-md-none";
  const logFileName = file ? filename(file) : "";

  let statusPanel;
  if (status === "success") {
    statusPanel = html`<${ResultsPanel} results="${results}" />`;
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
          style=${{
            display: "flex",
            paddingTop: 0,
            marginLeft: "0.5rem",
            minWidth: "350px",
          }}
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
                  display: "flex",
                }}
              >
                <i class=${icons.menu}></i>
              </button> `
            : ""}
          <div
            style=${{
              display: "flex",
              flexDirection: "column",
              marginLeft: "0.2rem",
            }}
          >
            <div
              style=${{
                marginTop: "0.1rem",
                display: "grid",
                gridTemplateColumns:
                  "minmax(30px,max-content) minmax(100px, max-content)",
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
                marginTop: "0.1rem",
                paddingBottom: 0,
                fontSize: "0.9rem",
                fontWeight: "300",
                display: "grid",
                gridTemplateColumns: "minmax(0,max-content) max-content",
              }}
            >
              <div
                class="navbar-secondary-text"
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
            marginBottom: "0",
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
          gridTemplateColumns: "1fr auto",
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
  const scorers = {};
  results.scores.map((score) => {
    scorers[score.name] = Object.keys(score.metrics).map((key) => {
      return { name: key, value: score.metrics[key].value };
    });
  });

  if (results.scores.length === 1) {
    const metrics = Object.values(scorers)[0];
    return html`<div
      style=${{
        display: "flex",
        flexDirection: "row",
        flexWrap: "wrap",
        justifyContent: "end",
        height: "100%",
        alignItems: "center",
      }}
    >
      ${metrics.map((metric, i) => {
        return html`<${VerticalMetric} metric=${metric} isFirst=${i === 0} />`;
      })}
    </div>`;
  } else {
    return html`<div
      style=${{
        display: "flex",
        flexDirection: "row",
        flexWrap: "wrap",
        justifyContent: "end",
        height: "100%",
        alignItems: "center",
        marginTop: "0.2rem",
        paddingBottom: "0.4rem",
        rowGap: "1em",
      }}
    >
      ${results.scores.map((score, index) => {
        return html`<${MultiScorerMetric}
          scorer=${score}
          isFirst=${index === 0}
        />`;
      })}
    </div>`;
  }
};

const VerticalMetric = ({ metric, isFirst }) => {
  return html`<div style=${{ paddingLeft: isFirst ? "0" : "1em" }}>
    <div
      style=${{
        fontSize: "0.8rem",
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
};

const MultiScorerMetric = ({ scorer, isFirst }) => {
  const baseFontSize = Object.keys(scorer.metrics).length === 1 ? 0.9 : 0.7;
  return html`<div style=${{ paddingLeft: isFirst ? "0" : "1.5em" }}>
    <div
      style=${{
        fontSize: `${baseFontSize}rem`,
        fontWeight: "200",
        textAlign: "center",
        borderBottom: "solid var(--bs-border-color) 1px",
        textTransform: "uppercase",
      }}
      class="multi-score-label"
    >
      ${scorer.name}
    </div>
    <div
      style=${{
        display: "grid",
        gridTemplateColumns: "auto auto",
        gridColumnGap: "0.3rem",
        gridRowGap: "0",
        fontSize: `${baseFontSize + 0.1}rem`,
      }}
    >
      ${Object.keys(scorer.metrics).map((key) => {
        const metric = scorer.metrics[key];
        return html` <div>${metric.name}</div>
          <div style=${{ fontWeight: "600" }}>
            ${formatPrettyDecimal(metric.value)}
          </div>`;
      })}
    </div>
  </div>`;
};
