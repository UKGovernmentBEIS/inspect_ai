import { html } from "htm/preact";

import { icons } from "../Constants.mjs";
import { LabeledValue } from "../components/LabeledValue.mjs";
import { formatPrettyDecimal } from "../utils/Format.mjs";

export const TitleBlock = ({
  title,
  subtitle,
  tertiaryTitle,
  log,
  metrics,
  _context,
}) => {
  if (!log) {
    return "";
  }

  const staticColStyle = {
    flexShrink: "0",
  };

  const expandingColStyle = {
    paddingRight: "0.5rem",
    paddingLeft: "0.5rem",
    overflow: "hidden",
  };
  const epochs = log.eval.config.epochs || 1;
  const hyperparameters = {
    ...log.plan.config,
    ...log.eval.task_args,
  };

  return html`
    <div style=${{ margin: "0", padding: "0.2em 1em 0.2em 1em" }}>
      <div
        class="row"
        style=${{ alignItems: "center", justifyContent: "space-between" }}
      >
        <div
          class="col font-title"
          style=${{
            flex: "0 1 1",
            display: "flex",
            marginRight: "auto",
            flexWrap: "wrap",
            alignItems: "baseline",
          }}
        >
          <span style=${{
            marginRight: "0.3rem",
            lineHeight: "1.6rem",
          }}>${title}</span>
          <span class="font-subtitle">${subtitle}</span>
          <span
            style=${{
              fontSize: "0.8rem",
              fontWeight: 300,
              flexBasis: "100%",
              marginTop: "0.2rem",
            }}
            >${tertiaryTitle}</span
          >
        </div>
        <div class="col" style=${{
          flex: "0 0 content",
          display: "flex",
          alignSelf: "end",
        }}>
          <${ResultsPanel} results="${metrics}" />
        </div>
      </div>
      <div class="row collapse show" id="title-plan-summary">
        <div style=${{
          display: "flex",
          paddingTop: "0.8rem",
          justifyContent: "space-between",
          paddingBottom: "0.2rem",
        }}>
        <${LabeledValue} label="Dataset" style=${staticColStyle}>
          <${DatasetSummary}
            dataset=${log.eval?.dataset}
            samples=${log.samples}
            epochs=${epochs}
            style=${{ fontSize: "0.8rem" }} />
        </${LabeledValue}>

        <${LabeledValue} label="Plan" style=${expandingColStyle} valueStyle=${{
    whiteSpace: "nowrap",
    textOverflow: "ellipsis",
    overflow: "hidden",
  }}>
          <${StepsSummary}
            steps=${log?.plan?.steps}
          />
        </${LabeledValue}>

        <${LabeledValue} label="Scorer" style=${staticColStyle}>
          <${ScorerSummary} 
          scorer=${log?.results?.scorer} />
        </${LabeledValue}>

        </div>
      </div>
      ${
        Object.keys(hyperparameters).length > 0
          ? html`
          <div class="row collapse show" id="title-hyperparameters" style=${{paddingTop: "0.5em", marginBottom: "0.2em"}}>
            <${LabeledValue} label="Hyperparameters">
              <${ParamSummary} params=${hyperparameters}/>
            </${LabeledValue}>
          </div>`
          : ""
      }

    </div>
  `;
};

const ResultsPanel = ({ results }) => {
  // Map the scores into a list of key/values
  const metrics = results
    ? Object.keys(results).map((key) => {
        return { name: key, value: results[key].value };
      })
    : [];

  return html`<div
    style=${{ display: "flex", flexDirection: "row", flexWrap: "wrap" }}
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

const DatasetSummary = ({ dataset, samples, epochs, style }) => {
  if (!dataset) {
    return "";
  }

  const sampleCount = epochs > 0 ? samples.length / epochs : samples;
  console

  return html`
    <div style=${style}>
      ${dataset.name}${samples?.length
        ? html` <span
            style=${{ fontSize: "0.9em" }}
          >
            ${dataset.name ? "— " : ""}${sampleCount + " "}${epochs > 1
              ? `x ${epochs} `
              : ""}
            ${samples.length === 1 ? "sample" : "samples"}</span
          >`
        : ""}
    </div>
  `;
};

const ScorerSummary = ({ scorer }) => {
  if (!scorer) {
    return "";
  }

  const summary = [];
  summary.push(scorer.name);
  return summary;
};

const StepsSummary = ({ steps }) => {
  if (!steps) {
    return "";
  }

  const stepNames = steps.map((step) => {
    return step.solver;
  });

  const summary = [];
  for (const stepName of stepNames) {
    if (summary.length > 0) {
      summary.push(
        html`<i
          class="${icons.arrows.right}"
          style=${{ marginLeft: "0.3em", marginRight: "0.3em" }}
        ></i>`
      );
    }
    summary.push(stepName);
  }
  return summary;
};

const ParamSummary = ({ params }) => {
  if (!params) {
    return "";
  }
  const paraValues = Object.keys(params).map((key) => {
    return `${key}: ${params[key]}`;
  });
  if (paraValues.length > 0) {
    return html`<code style=${{padding: 0, color: "var(--bs-body-color)"}}>${paraValues.join(", ")}</code>`;
  } else {
    return "";
  }
};
