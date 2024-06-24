import { html } from "htm/preact";

import { toTitleCase } from "../utils/Format.mjs";
import { ghCommitUrl } from "../utils/Git.mjs";
import { icons } from "../Constants.mjs";
import { Card, CardBody } from "../components/Card.mjs";
import { MetaDataView } from "../components/MetaDataView.mjs";
import { CardHeader } from "../components/Card.mjs";

const kPlanCardBodyId = "task-plan-card-body";

export const PlanCard = ({ log, context }) => {
  return html`
    <${Card}>
      <${CardHeader} icon=${icons.config} label="Config"/>
      <${CardBody} id="${kPlanCardBodyId}" style=${{
        paddingTop: "0",
        paddingBottom: "0",
        borderTop: "solid var(--bs-border-color) 1px",
      }}>
        <${PlanDetailView}
          evaluation=${log?.eval}
          plan=${log?.plan}
          scorer=${log?.results?.scorer}
          context=${context}
        />
      </${CardBody}>
    </${Card}>
  `;
};

const planItemStyle = {
  fontSize: "0.9rem",
  marginBottom: "0em",
};

const planSepStyle = {
  marginLeft: ".3em",
  marginRight: ".3em",
  marginTop: "em",
  marginBottom: "-0.1em",
};

const ScorerDetailVew = ({ scorer, context }) => {
  return html`<${DetailStep}
    icon=${icons.scorer}
    name=${scorer?.name}
    params=${scorer?.params}
    context=${context}
    style=${planItemStyle}
  />`;
};

const DatasetDetailView = ({ dataset, context, style }) => {
  if (!dataset || Object.keys(dataset).length === 0) {
    return html`<span style=${{ ...planItemStyle, ...style }}
      >No dataset information available</span
    >`;
  }

  return html`<${MetaDataView}
    entries="${dataset}"
    tableOptions="borderless,sm"
    context=${context}
    style=${{ ...planItemStyle, ...style }}
  />`;
};

const SolversDetailView = ({ steps, context }) => {
  const separator = html` <div style=${{ ...planItemStyle, ...planSepStyle }}>
    <i class="${icons.arrows.right}"></i>
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
          style=${{ fontSize: "0.8rem" }}
        />`}
      </div>
    </div>
  `;
};

const PlanDetailView = ({ evaluation, plan, context, scorer }) => {
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

  if (evaluation?.model) {
    config["model"] = evaluation.model;
  }

  if (evaluation?.model_base_url) {
    config["model_base_url"] = evaluation.model_base_url;
  }

  if (evaluation?.tool_environment) {
    config["tool_environment"] = evaluation.tool_environment[0];
    if (evaluation.tool_environment[1]) {
      config["tool_environment_config"] = evaluation.tool_environment[1];
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
    fontSize: "0.8rem",
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
      <${SolversDetailView}
        steps=${steps}
        context=${context}
        scorer=${scorer}
      />
    `,
  });

  if (scorer) {
    taskColumns.push({
      title: "Scorer",
      style: floatingColumnStyle,
      contents: html`
        <${ScorerDetailVew} context=${context} scorer=${scorer} />
      `,
    });
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
  const configColumnStyle = cols.length === 1 ? oneColumnStyle : twoColumnStyle;

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
        class="row"
        style=${{
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
      <div class="card-subheading">${title}</div>
      ${children}
    </div>
  `;
};
