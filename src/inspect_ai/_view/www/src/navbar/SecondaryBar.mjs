import { html } from "htm/preact";

import { LabeledValue } from "../components/LabeledValue.mjs";
import { formatDataset } from "../utils/Format.mjs";

export const SecondaryBar = ({ log, status, style }) => {
  if (!log || status !== "success") {
    return "";
  }

  const staticColStyle = {
    flexShrink: "0",
  };

  const epochs = log.eval.config.epochs || 1;
  const hyperparameters = {
    ...log.plan.config,
    ...log.eval.task_args,
  };

  const hasConfig = Object.keys(hyperparameters).length > 0;

  const values = [];
  values.push({
    size: "minmax(12%, auto)",
    value: html`<${LabeledValue} label="Dataset" style=${staticColStyle}>
    <${DatasetSummary}
      dataset=${log.eval?.dataset}
      samples=${log.samples}
      epochs=${epochs} />
  </${LabeledValue}>
`,
  });

  const label = log?.results?.scores.length > 1 ? "Scorers" : "Scorer";
  values.push({
    size: "minmax(12%, auto)",
    value: html`<${LabeledValue} label="${label}" style=${staticColStyle} style=${{ justifySelf: hasConfig ? "center" : "right" }}>
    <${ScorerSummary} 
      scorers=${log?.results?.scores} />
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

  return html`
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
        ...style,
      }}
    >
      ${values.map((val) => {
        return val.value;
      })}
    </div>
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

const ParamSummary = ({ params }) => {
  if (!params) {
    return "";
  }
  const paraValues = Object.keys(params).map((key) => {
    return `${key}: ${params[key]}`;
  });
  if (paraValues.length > 0) {
    return html`<code style=${{ padding: 0, color: "var(--bs-body-color)" }}
      >${paraValues.join(", ")}</code
    >`;
  } else {
    return "";
  }
};
