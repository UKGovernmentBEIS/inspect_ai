import { html } from "htm/preact";

import { toTitleCase } from "../utils/Format.mjs";
import { ghCommitUrl } from "../utils/Git.mjs";
import { ApplicationIcons } from "../appearance/Icons.mjs";
import { FontSize, TextStyle } from "../appearance/Fonts.mjs";
import { Card, CardBody } from "../components/Card.mjs";
import { MetaDataView } from "../components/MetaDataView.mjs";
import { CardHeader } from "../components/Card.mjs";

const kPlanCardBodyId = "task-plan-card-body";

/**
 * Renders the plan card
 *
 * @param {Object} props - The parameters for the component.
 * @param {import("../types/log").EvalSpec} [props.evalSpec] - The sample
 * @param {import("../types/log").EvalPlan} [props.evalPlan] - The task id
 * @param {import("../types/log").EvalScore[]} [props.scores] - the samples
 * @param {import("../Types.mjs").RenderContext} props.context - is this off canvas
 *
 * @returns {import("preact").JSX.Element} The TranscriptView component.
 */
export const PlanCard = ({ evalSpec, evalPlan, scores, context }) => {
  return html`
    <${Card}>
      <${CardHeader} icon=${ApplicationIcons.config} label="Config"/>
      <${CardBody} id="${kPlanCardBodyId}" style=${{
        paddingTop: "0",
        paddingBottom: "0",
      }}>
      
        <${PlanDetailView}
          evaluation=${evalSpec}
          plan=${evalPlan}
          scores=${scores}
          context=${context}
        />
      </${CardBody}>
    </${Card}>
  `;
};

const planItemStyle = {
  fontSize: FontSize.base,
  marginBottom: "0em",
};

const planSepStyle = {
  marginLeft: ".3em",
  marginRight: ".3em",
  marginTop: "em",
  marginBottom: "-0.1em",
};

const ScorerDetailView = ({ name, scores, params, context }) => {
  // Merge scores into params
  if (scores.length > 1) {
    params["scores"] = scores;
  }

  return html`<${DetailStep}
    icon=${ApplicationIcons.scorer}
    name=${name}
    params=${params}
    context=${context}
    style=${planItemStyle}
  />`;
};

const DatasetDetailView = ({ dataset, context, style }) => {
  // Filter out sample_ids
  const filtered = Object.fromEntries(
    Object.entries(dataset).filter(([key]) => key !== "sample_ids"),
  );

  if (!dataset || Object.keys(filtered).length === 0) {
    return html`<span style=${{ ...planItemStyle, ...style }}
      >No dataset information available</span
    >`;
  }

  return html`<${MetaDataView}
    entries="${filtered}"
    tableOptions="borderless,sm"
    context=${context}
    style=${{ ...planItemStyle, ...style }}
  />`;
};

const SolversDetailView = ({ steps, context }) => {
  const separator = html` <div style=${{ ...planItemStyle, ...planSepStyle }}>
    <i class="${ApplicationIcons.arrows.right}"></i>
  </div>`;

  const details = steps?.map((step, index) => {
    return html`
      <${DetailStep}
        name=${step.solver}
        context=${context}
        style=${planItemStyle}
      />
      ${index < steps.length - 1 ? separator : ""}
    `;
  });

  return html`<div
    style=${{
      display: "flex",
      flexDirection: "columns",
    }}
  >
    ${details}
  </div>`;
};

const DetailStep = ({ icon, name, params, style, context }) => {
  const iconHtml = icon
    ? html`<i class="${icon}" style=${{ marginRight: ".3em" }}></i>`
    : "";
  return html`
    <div style=${style}>
      ${iconHtml} ${name}
      <div
        style=${{
          marginLeft: "1.3rem",
          marginTop: "0.2rem",
          marginBottom: "0.3rem",
        }}
      >
        ${html`<${MetaDataView}
          entries="${params}"
          context=${context}
          style=${{ fontSize: FontSize.small }}
        />`}
      </div>
    </div>
  `;
};

const PlanDetailView = ({ evaluation, plan, context, scores }) => {
  if (!evaluation) {
    return "";
  }

  const config = evaluation?.config || {};
  const steps = plan?.steps;
  const metadata = evaluation?.metadata;
  const revision = evaluation?.revision;
  const packages = evaluation?.packages;
  const model_args = evaluation?.model_args;
  const task_args = evaluation?.task_args;
  const generate_config = plan?.config;

  const taskInformation = {
    ["Task ID"]: evaluation?.task_id,
    ["Run ID"]: evaluation?.run_id,
  };
  if (revision) {
    taskInformation[
      `${revision.type ? `${toTitleCase(revision.type)} ` : ""}Revision`
    ] = {
      _html: html`<a href="${ghCommitUrl(revision.origin, revision.commit)}"
        >${revision.commit}</a
      >`,
    };
  }
  if (packages) {
    taskInformation["Inspect"] = {
      _html: html`${Object.keys(packages)
        .map((key) => {
          return `${key} ${packages[key]}`;
        })
        .join("<br/>\n")}`,
    };
  }
  if (evaluation.tags) {
    taskInformation["Tags"] = evaluation.tags.join(", ");
  }

  if (evaluation?.model) {
    config["model"] = evaluation.model;
  }

  if (evaluation?.model_base_url) {
    config["model_base_url"] = evaluation.model_base_url;
  }

  if (evaluation?.sandbox) {
    config["sandbox"] = evaluation.sandbox[0];
    if (evaluation.sandbox[1]) {
      config["sandbox_config"] = evaluation.sandbox[1];
    }
  }

  const floatingColumnStyle = {
    flex: "0 1 1",
    width: "unset",
    textAlign: "left",
    paddingLeft: "0.6rem",
    paddingRight: "0.6rem",
  };

  const wideColumnStyle = {
    flex: "1 1 1",
    width: "unset",
    paddingLeft: "0.6rem",
    paddingRight: "0.6rem",
  };

  const oneColumnStyle = {
    flex: "0 0 100%",
  };

  const twoColumnStyle = {
    flex: "0 0 50%",
  };

  const planMetadataStyle = {
    fontSize: FontSize.base,
  };

  const taskColumns = [];
  taskColumns.push({
    title: "Dataset",
    style: floatingColumnStyle,
    contents: html`<${DatasetDetailView}
      dataset=${evaluation.dataset}
      context=${context}
    />`,
  });

  taskColumns.push({
    title: "Plan",
    style: wideColumnStyle,
    contents: html`
      <${SolversDetailView} steps=${steps} context=${context} />
    `,
  });

  if (scores) {
    const scorers = scores.reduce((accum, score) => {
      if (!accum[score.scorer]) {
        accum[score.scorer] = {
          scores: [score.name],
          params: score.params,
        };
      } else {
        accum[score.scorer].scores.push(score.name);
      }
      return accum;
    }, {});

    if (Object.keys(scorers).length > 0) {
      const label = Object.keys(scorers).length === 1 ? "Scorer" : "Scorers";
      const scorerPanels = Object.keys(scorers).map((key) => {
        return html`<${ScorerDetailView}
          name=${key}
          scores=${scorers[key].scores}
          params=${scorers[key].params}
          context=${context}
        />`;
      });

      taskColumns.push({
        title: label,
        style: floatingColumnStyle,
        contents: scorerPanels,
      });
    }
  }

  // Compute the column style for the remaining (either 1 or 2 columns wide)
  const metadataColumns = [];
  const cols = colCount(
    metadataColumns,
    task_args,
    model_args,
    config,
    metadata,
  );
  const configColumnStyle = cols === 1 ? oneColumnStyle : twoColumnStyle;

  metadataColumns.push({
    title: "Task Information",
    style: configColumnStyle,
    contents: html`
      <${MetaDataView}
        style=${planMetadataStyle}
        classes="task-title-deets-grid"
        entries="${taskInformation}"
        tableOptions="borderless,sm"
        context=${context}
      />
    `,
  });

  if (task_args && Object.keys(task_args).length > 0) {
    metadataColumns.push({
      title: "Task Args",
      style: configColumnStyle,
      contents: html`
        <${MetaDataView}
          style=${planMetadataStyle}
          classes="task-plan-task-args-grid"
          entries="${task_args}"
          tableOptions="sm"
          context=${context}
        />
      `,
    });
  }
  if (model_args && Object.keys(model_args).length > 0) {
    metadataColumns.push({
      title: "Model Args",
      style: configColumnStyle,
      contents: html`
        <${MetaDataView}
          style=${planMetadataStyle}
          classes="task-plan-model-args-grid"
          entries="${model_args}"
          tableOptions="sm"
          context=${context}
        />
      `,
    });
  }

  if (config && Object.keys(config).length > 0) {
    metadataColumns.push({
      title: "Configuration",
      style: configColumnStyle,
      contents: html`
        <${MetaDataView}
          style=${planMetadataStyle}
          classes="task-plan-configuration"
          entries="${config}"
          tableOptions="sm"
          context=${context}
        />
      `,
    });
  }

  if (generate_config && Object.keys(generate_config).length > 0) {
    metadataColumns.push({
      title: "Generate Config",
      style: configColumnStyle,
      contents: html`
        <${MetaDataView}
          style=${planMetadataStyle}
          classes="task-plan-generate-configuration"
          entries="${generate_config}"
          tableOptions="sm"
          context=${context}
        />
      `,
    });
  }

  if (metadata && Object.keys(metadata).length > 0) {
    metadataColumns.push({
      title: "Metadata",
      style: configColumnStyle,
      contents: html`
        <${MetaDataView}
          style=${planMetadataStyle}
          classes="task-plan-metadata"
          entries="${metadata}"
          tableOptions="sm"
          context=${context}
        />
      `,
    });
  }

  return html`
    <div style=${{ paddingTop: "0", paddingBottom: "1em", marginLeft: "0" }}>
      <div
        style=${{
          display: "grid",
          gridTemplateColumns: `repeat(${taskColumns.length}, auto)`,
          justifyContent: "space-between",
          flexWrap: "wrap",
          paddingBottom: "0.7rem",
          borderBottom: "solid 1px var(--bs-border-color)",
        }}
      >
        ${taskColumns.map((col) => {
          return html`<${PlanColumn} title="${col.title}" style=${col.style}>
        ${col.contents}
      </${PlanColumn}>
      `;
        })}
      </div>

      <div
        class="row"
        style=${{ justifyContent: "flex-start", flexWrap: "wrap" }}
      >
        ${metadataColumns.map((col) => {
          return html`<${PlanColumn} title="${col.title}" style=${col.style}>
            ${col.contents}
          </${PlanColumn}>
          `;
        })}
      </div>
    </div>
  `;
};

const colCount = (...other) => {
  let count = 0;
  for (const o in other) {
    if (o && Object.keys(o).length > 0) {
      count++;
    }
  }
  return count;
};

const PlanColumn = ({ title, classes, style, children }) => {
  return html`
    <div class="${classes || ""}" ...${{ style }}>
      <div
        class="card-subheading"
        style=${{
          fontSize: FontSize.small,
          ...TextStyle.label,
          ...TextStyle.secondary,
          marginTop: "1em",
        }}
      >
        ${title}
      </div>
      ${children}
    </div>
  `;
};
