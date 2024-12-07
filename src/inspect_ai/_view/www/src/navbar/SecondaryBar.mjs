import { html } from "htm/preact";

import { LabeledValue } from "../components/LabeledValue.mjs";
import { formatDataset, formatDuration } from "../utils/Format.mjs";
import { ExpandablePanel } from "../components/ExpandablePanel.mjs";

/**
 * Renders the Navbar
 *
 * @param {Object} props - The parameters for the component.
 * @param {import("../types/log").EvalSpec} [props.evalSpec] - The EvalSpec
 * @param {import("../types/log").EvalPlan} [props.evalPlan] - The EvalSpec
 * @param {import("../types/log").EvalResults} [props.evalResults] - The EvalResults
 * @param {import("../types/log").EvalStats} [props.evalStats] - The EvalStats
 * @param {import("../api/Types.mjs").SampleSummary[]} [props.samples] - the samples
 * @param {string} [props.status] - the status
 * @param {Map<string, string>} [props.style] - is this off canvas
 *
 * @returns {import("preact").JSX.Element | string} The TranscriptView component.
 */
export const SecondaryBar = ({
  evalSpec,
  evalPlan,
  evalResults,
  evalStats,
  samples,
  status,
  style,
}) => {
  if (!evalSpec || status !== "success") {
    return "";
  }

  const staticColStyle = {
    flexShrink: "0",
  };

  const epochs = evalSpec.config.epochs || 1;
  const hyperparameters = {
    ...evalPlan?.config,
    ...evalSpec.task_args,
  };

  const hasConfig = Object.keys(hyperparameters).length > 0;

  const values = [];

  values.push({
    size: "minmax(12%, auto)",
    value: html`<${LabeledValue} label="Dataset" style=${staticColStyle}>
    <${DatasetSummary}
      dataset=${evalSpec.dataset}
      samples=${samples}
      epochs=${epochs} />
  </${LabeledValue}>
`,
  });

  const label = evalResults?.scores.length > 1 ? "Scorers" : "Scorer";
  values.push({
    size: "minmax(12%, auto)",
    value: html`<${LabeledValue} label="${label}" style=${staticColStyle} style=${{ justifySelf: hasConfig ? "left" : "center" }}>
    <${ScorerSummary} 
      scorers=${evalResults?.scores} />
  </${LabeledValue}>`,
  });

  if (hasConfig) {
    values.push({
      size: "minmax(12%, auto)",
      value: html`<${LabeledValue} label="Config" style=${{ justifySelf: "right" }}>
      <${ParamSummary} params=${hyperparameters}/>
    </${LabeledValue}>`,
    });
  }

  const totalDuration = formatDuration(
    new Date(evalStats.started_at),
    new Date(evalStats.completed_at),
  );
  values.push({
    size: "minmax(12%, auto)",
    value: html`
      <${LabeledValue} label="Duration" style=${{ justifySelf: "right" }}>
        ${totalDuration}
      </${LabeledValue}>`,
  });

  return html`
    <${ExpandablePanel} style=${{ margin: "0", ...style }} collapse=${true} lines=${4}>
    <div
      style=${{
        margin: "0",
        padding: "0.2em 1em 0.2em 1em",
        display: "grid",
        gridColumnGap: "1em",
        borderTop: "1px solid var(--bs-border-color)",
        gridTemplateColumns: `${values
          .map((val) => {
            return val.size;
          })
          .join(" ")}`,
      }}
    >
      ${values.map((val) => {
        return val.value;
      })}
    </div>
    </${ExpandablePanel}>
  `;
};

const DatasetSummary = ({ dataset, samples, epochs, style }) => {
  if (!dataset) {
    return "";
  }

  return html`
    <div style=${style}>
      ${dataset.name}${samples?.length
        ? html`${formatDataset(dataset.name, samples.length, epochs)}`
        : ""}
    </div>
  `;
};

const ScorerSummary = ({ scorers }) => {
  if (!scorers) {
    return "";
  }

  const uniqScorers = new Set();
  scorers.forEach((scorer) => {
    uniqScorers.add(scorer.name);
  });

  return Array.from(uniqScorers).join(", ");
};

/**
 * A component that displays a summary of parameters.
 *
 * @param {Object} props - The component props.
 * @param {Record<string, any>} props.params - An object containing key-value pairs representing parameters.
 * @returns {import("preact").JSX.Element | string} The component.
 */
const ParamSummary = ({ params }) => {
  if (!params) {
    return "";
  }
  const paraValues = Object.keys(params).map((key) => {
    const val = params[key];
    if (Array.isArray(val) || typeof val === "object") {
      return `${key}: ${JSON.stringify(val)}`;
    } else {
      return `${key}: ${val}`;
    }
  });
  if (paraValues.length > 0) {
    return html`<code style=${{ padding: 0, color: "var(--bs-body-color)" }}
      >${paraValues.join(", ")}</code
    >`;
  } else {
    return "";
  }
};
