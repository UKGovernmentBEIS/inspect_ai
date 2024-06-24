import { html } from "htm/preact";

import { LabeledValue } from "../components/LabeledValue.mjs";
import { formatDataset } from "../utils/Format.mjs";

export const TitleBlock = ({ log, status }) => {
  if (!log) {
    return "";
  }

  if (status !== "success") {
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

  const values = [];
  values.push({
    size: "auto",
    value: html`<${LabeledValue} label="Dataset" style=${staticColStyle}>
    <${DatasetSummary}
      dataset=${log.eval?.dataset}
      samples=${log.samples}
      epochs=${epochs}
      style=${{ fontSize: "0.8rem" }} />
  </${LabeledValue}>
`,
  });

  values.push({
    size: "auto",
    value: html`<${LabeledValue} label="Scorer" style=${staticColStyle}>
    <${ScorerSummary} 
    scorer=${log?.results?.scorer} />
  </${LabeledValue}>`,
  });

  if (Object.keys(hyperparameters).length > 0) {
    values.push({
      size: "auto",
      value: html`<${LabeledValue} label="Config">
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
        paddingTop: "0.5em",
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
  `;
};

const DatasetSummary = ({ dataset, samples, epochs, style }) => {
  if (!dataset) {
    return "";
  }

  return html`
    <div style=${style}>
      ${dataset.name}${samples?.length
        ? html` <span style=${{ fontSize: "0.9em" }}>
            ${formatDataset(dataset.name, samples.length, epochs)}
          </span>`
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
