import { EvalPlan, EvalScore, EvalSpec, Params2 } from "../../@types/log";
import { toTitleCase } from "../../utils/format";
import { ghCommitUrl } from "../../utils/git";
import { MetaDataView } from "../content/MetaDataView";
import { DatasetDetailView } from "./DatasetDetailView";
import { ScorerDetailView } from "./ScorerDetailView";
import { SolversDetailView } from "./SolverDetailView";

import clsx from "clsx";
import { FC, ReactNode } from "react";
import { kModelNone } from "../../constants";
import styles from "./PlanDetailView.module.css";

interface PlanDetailViewProps {
  evaluation?: EvalSpec;
  plan?: EvalPlan;
  scores?: EvalScore[];
}

export const PlanDetailView: FC<PlanDetailViewProps> = ({
  evaluation,
  plan,
  scores,
}) => {
  if (!evaluation) {
    return null;
  }

  // Add configuration
  const config: Record<string, unknown> = {};
  Object.entries(evaluation?.config || {}).forEach((entry) => {
    const key = entry[0];
    const value = entry[1];
    config[key] = value;
  });

  const steps = plan?.steps;
  const metadata = evaluation?.metadata;
  const revision = evaluation?.revision;
  const packages = evaluation?.packages;
  const model_args = evaluation?.model_args;
  const task_args = evaluation?.task_args;
  const generate_config = plan?.config;

  const taskInformation: Record<string, unknown> = {
    ["Task ID"]: evaluation?.task_id,
    ["Run ID"]: evaluation?.run_id,
  };
  if (revision) {
    taskInformation[
      `${revision.type ? `${toTitleCase(revision.type)} ` : ""}Revision`
    ] = {
      _html: (
        <a href={ghCommitUrl(revision.origin, revision.commit)}>
          {revision.commit}
        </a>
      ),
    };
  }
  if (packages) {
    const names = Object.keys(packages).map((key) => {
      return `${key} ${packages[key]}`;
    });

    if (names.length === 1) {
      taskInformation["Inspect"] = names[0];
    } else {
      taskInformation["Inspect"] = names;
    }
  }
  if (evaluation.tags) {
    taskInformation["Tags"] = evaluation.tags.join(", ");
  }

  if (evaluation?.model && evaluation.model !== kModelNone) {
    config["model"] = evaluation.model;
  }

  if (evaluation?.model_base_url) {
    config["model_base_url"] = evaluation.model_base_url;
  }

  if (evaluation?.sandbox) {
    if (Array.isArray(evaluation?.sandbox)) {
      config["sandbox"] = evaluation.sandbox[0];
      if (evaluation.sandbox[1]) {
        config["sandbox_config"] = evaluation.sandbox[1];
      }
    } else {
      config["sandbox"] = evaluation?.sandbox.type;
      config["sandbox_config"] = evaluation?.sandbox.config;
    }
  }

  const taskColumns: {
    title: string;
    className: string | string[];
    contents: ReactNode;
  }[] = [];
  taskColumns.push({
    title: "Dataset",
    className: styles.floatingCol,
    contents: <DatasetDetailView dataset={evaluation.dataset} />,
  });

  if (steps) {
    taskColumns.push({
      title: "Solvers",
      className: styles.wideCol,
      contents: <SolversDetailView steps={steps} />,
    });
  }

  if (scores) {
    const scorers = scores.reduce(
      (accum, score) => {
        if (!accum[score.scorer]) {
          accum[score.scorer] = {
            scores: [score.name],
            params: score.params,
          };
        } else {
          accum[score.scorer].scores.push(score.name);
        }
        return accum;
      },
      {} as Record<string, { scores: string[]; params: Params2 }>,
    );

    if (Object.keys(scorers).length > 0) {
      const label = Object.keys(scorers).length === 1 ? "Scorer" : "Scorers";
      const scorerPanels = Object.keys(scorers).map((key) => {
        return (
          <ScorerDetailView
            key={key}
            name={key}
            scores={scorers[key].scores}
            params={scorers[key].params as Record<string, unknown>}
          />
        );
      });

      taskColumns.push({
        title: label,
        className: styles.floatingCol,
        contents: scorerPanels,
      });
    }
  }

  // Compute the column style for the remaining (either 1 or 2 columns wide)
  const metadataColumns: {
    title: string;
    className: string;
    contents: ReactNode;
  }[] = [];
  const cols = colCount(
    metadataColumns,
    task_args,
    model_args,
    config,
    metadata,
  );

  metadataColumns.push({
    title: "Task Information",
    className: cols === 1 ? styles.oneCol : styles.twoCol,
    contents: (
      <MetaDataView
        key={`plan-md-task`}
        className={"text-size-small"}
        entries={taskInformation}
        tableOptions="sm"
      />
    ),
  });

  if (task_args && Object.keys(task_args).length > 0) {
    metadataColumns.push({
      title: "Task Args",
      className: cols === 1 ? styles.oneCol : styles.twoCol,
      contents: (
        <MetaDataView
          key={`plan-md-task-args`}
          className={"text-size-small"}
          entries={task_args as Record<string, unknown>}
          tableOptions="sm"
        />
      ),
    });
  }
  if (model_args && Object.keys(model_args).length > 0) {
    metadataColumns.push({
      title: "Model Args",
      className: cols === 1 ? styles.oneCol : styles.twoCol,
      contents: (
        <MetaDataView
          key={`plan-md-model-args`}
          className={"text-size-small"}
          entries={model_args as Record<string, unknown>}
          tableOptions="sm"
        />
      ),
    });
  }

  if (config && Object.keys(config).length > 0) {
    metadataColumns.push({
      title: "Configuration",
      className: cols === 1 ? styles.oneCol : styles.twoCol,
      contents: (
        <MetaDataView
          key={`plan-md-config`}
          className={"text-size-small"}
          entries={config}
          tableOptions="sm"
        />
      ),
    });
  }

  if (generate_config && Object.keys(generate_config).length > 0) {
    const generate_record: Record<string, unknown> = Object.fromEntries(
      Object.entries(generate_config),
    );

    metadataColumns.push({
      title: "Generate Config",
      className: cols === 1 ? styles.oneCol : styles.twoCol,
      contents: (
        <MetaDataView
          key={`plan-md-generate-config`}
          className={"text-size-small"}
          entries={generate_record}
          tableOptions="sm"
        />
      ),
    });
  }

  if (metadata && Object.keys(metadata).length > 0) {
    metadataColumns.push({
      title: "Metadata",
      className: cols === 1 ? styles.oneCol : styles.twoCol,
      contents: (
        <MetaDataView
          key={`plan-md-metadata`}
          className={"text-size-small"}
          entries={metadata}
          tableOptions="sm"
        />
      ),
    });
  }

  return (
    <div className={styles.container}>
      <div
        className={styles.grid}
        style={{
          gridTemplateColumns: `repeat(${taskColumns.length}, auto)`,
        }}
      >
        {taskColumns.map((col) => {
          return (
            <PlanColumn
              title={col.title}
              className={col.className}
              key={`plan-col-${col.title}`}
            >
              {col.contents}
            </PlanColumn>
          );
        })}
      </div>

      <div className={clsx(styles.row)}>
        {metadataColumns.map((col) => {
          return (
            <PlanColumn
              title={col.title}
              className={col.className}
              key={`plan-col-${col.title}`}
            >
              {col.contents}
            </PlanColumn>
          );
        })}
      </div>
    </div>
  );
};

const colCount = (...other: unknown[]) => {
  let count = 0;
  for (const o in other) {
    if (o && Object.keys(o).length > 0) {
      count++;
    }
  }
  return count;
};

interface PlanColumnProps {
  title: string;
  className: string | string[];
  children: ReactNode;
}

const PlanColumn: FC<PlanColumnProps> = ({ title, className, children }) => {
  return (
    <div className={clsx(className)}>
      <div
        className={clsx(
          "card-subheading",
          "text-size-small",
          "text-style-label",
          "text-style-secondary",
          styles.planCol,
        )}
      >
        {title}
      </div>
      {children}
    </div>
  );
};
