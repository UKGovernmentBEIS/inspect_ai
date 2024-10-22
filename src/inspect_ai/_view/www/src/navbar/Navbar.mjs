import { html } from "htm/preact";

import { ApplicationIcons } from "./../appearance/Icons.mjs";
import { ApplicationStyles } from "./../appearance/Styles.mjs";
import { FontSize, TextStyle } from "../appearance/Fonts.mjs";
import { filename } from "./../utils/Path.mjs";
import { formatPrettyDecimal } from "../utils/Format.mjs";

import { CopyButton } from "./../components/CopyButton.mjs";
import { SecondaryBar } from "./SecondaryBar.mjs";

/**
 * Renders the Navbar
 *
 * @param {Object} props - The parameters for the component.
 * @param {string} [props.file] - The file name
 * @param {import("../types/log").EvalSpec} [props.evalSpec] - The EvalSpec
 * @param {import("../types/log").EvalResults} [props.evalResults] - The EvalResults
 * @param {import("../types/log").EvalPlan} [props.evalPlan] - The EvalSpec
 * @param {import("../api/Types.mjs").SampleSummary[]} [props.samples] - the samples
 * @param {string} [props.status] - the status
 * @param {boolean} props.offcanvas - Are we in offcanvas mode?
 * @param {boolean} props.showToggle - Should we show the toggle?
 *
 * @returns {import("preact").JSX.Element} The TranscriptView component.
 */
export const Navbar = ({
  file,
  evalSpec,
  evalPlan,
  evalResults,
  samples,
  showToggle,
  offcanvas,
  status,
}) => {
  const toggleOffCanClass = offcanvas ? "" : " d-md-none";
  const logFileName = file ? filename(file) : "";

  const task = evalSpec?.task;
  const model = evalSpec?.model;
  const results = evalResults;
  const created = evalSpec?.created;

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
            minWidth: "250px",
          }}
        >
          ${showToggle
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
                <i class=${ApplicationIcons.menu}></i>
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
                id="task-title"
                style=${{
                  fontWeight: 600,
                  marginRight: "0.3rem",
                  ...ApplicationStyles.wrapText(),
                }}
                class="task-title"
                title=${task}
              >
                ${task}
              </div>
              <div
                id="task-model"
                style=${{
                  fontSize: FontSize.base,
                  paddingTop: "0.4rem",
                  ...ApplicationStyles.wrapText(),
                }}
                class="task-model"
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
                fontSize: FontSize.small,
                display: "grid",
                gridTemplateColumns: "minmax(0,max-content) max-content",
              }}
            >
              <div
                class="navbar-secondary-text"
                style=${{
                  ...ApplicationStyles.wrapText(),
                }}
              >
                ${logFileName}
              </div>
              <${CopyButton} value=${file} />
            </div>
          </div>
        </div>

        <div id="task-created" style=${{ display: "none" }}>${created}</div>

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
        <${SecondaryBar}
          evalSpec=${evalSpec}
          evalPlan=${evalPlan}
          evalResults=${evalResults}
          samples=${samples}
          status=${status}
          style=${{ gridColumn: "1/-1" }}
        />
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
      fontSize: FontSize.smaller,
    }}
  >
    <i
      class="${ApplicationIcons.logging.info}"
      style=${{ fontSize: FontSize.large, marginRight: "0.3em" }}
    />
    cancelled (${sampleCount} ${sampleCount === 1 ? "sample" : "samples"})
  </div>`;
};

const RunningPanel = () => {
  return html`
    <div
      style=${{
        marginTop: "0.5em",
        display: "inline-grid",
        gridTemplateColumns: "max-content max-content",
      }}
    >
      <div>
        <i class=${ApplicationIcons.running} />
      </div>
      <div
        style=${{
          marginLeft: "0.3em",
          paddingTop: "0.2em",
          fontSize: FontSize.smaller,
          ...TextStyle.label,
          ...TextStyle.secondary,
        }}
      >
        Running
      </div>
    </div>
  `;
};

const ResultsPanel = ({ results }) => {
  // Map the scores into a list of key/values
  if (results?.scores?.length === 1) {
    const scorers = {};
    results.scores.map((score) => {
      scorers[score.name] = Object.keys(score.metrics).map((key) => {
        return {
          name: key,
          value: score.metrics[key].value,
          reducer: score.reducer,
        };
      });
    });

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
      ${results?.scores?.map((score, index) => {
        return html`<${MultiScorerMetric}
          scorer=${score}
          isFirst=${index === 0}
        />`;
      })}
    </div>`;
  }
};

const VerticalMetric = ({ metric, isFirst }) => {
  const reducer_component = metric.reducer
    ? html` <div
        style=${{
          fontSize: FontSize.smaller,
          textAlign: "center",
          paddingTop: "0.3rem",
          marginBottom: "-0.3rem",
          ...TextStyle.label,
          ...TextStyle.secondary,
        }}
      >
        ${metric.reducer}
      </div>`
    : "";

  return html`<div style=${{ paddingLeft: isFirst ? "0" : "1em" }}>
    <div
      class="vertical-metric-label"
      style=${{
        fontSize: FontSize.smaller,
        ...TextStyle.secondary,
        textAlign: "center",
        paddingTop: "0.3rem",
        marginBottom: "-0.2rem",
        ...TextStyle.label,
        ...TextStyle.secondary,
        borderBottom: "solid var(--bs-border-color) 1px",
      }}
    >
      ${metric.name}
    </div>
    ${reducer_component}
    <div
      class="vertical-metric-value"
      style=${{
        fontSize: FontSize.larger,
        fontWeight: "500",
        textAlign: "center",
      }}
    >
      ${formatPrettyDecimal(metric.value)}
    </div>
  </div>`;
};

const MultiScorerMetric = ({ scorer, isFirst }) => {
  const titleFontSize =
    Object.keys(scorer.metrics).length === 1 ? FontSize.larger : FontSize.base;
  const reducerFontSize =
    Object.keys(scorer.metrics).length === 1
      ? FontSize.small
      : FontSize.smaller;
  const valueFontSize =
    Object.keys(scorer.metrics).length === 1 ? FontSize.base : FontSize.base;

  const reducer_component = scorer.reducer
    ? html`<div
        style=${{
          fontSize: reducerFontSize,
          textAlign: "center",
          marginBottom: "-0.3rem",
          ...TextStyle.label,
          ...TextStyle.secondary,
        }}
      >
        ${scorer.reducer}
      </div>`
    : "";

  return html`<div style=${{ paddingLeft: isFirst ? "0" : "1.5em" }}>
    <div
      style=${{
        fontSize: titleFontSize,
        textAlign: "center",
        borderBottom: "solid var(--bs-border-color) 1px",
        marginBottom: "-0.1rem",
        ...TextStyle.label,
        ...TextStyle.secondary,
      }}
      class="multi-score-label"
    >
      ${scorer.name}
    </div>
    ${reducer_component}
    <div
      style=${{
        display: "grid",
        gridTemplateColumns: "auto auto",
        gridColumnGap: "0.3rem",
        gridRowGap: "0",
        fontSize: valueFontSize,
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
