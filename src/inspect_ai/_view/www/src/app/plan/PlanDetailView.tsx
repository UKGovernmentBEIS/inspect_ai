import { EvalPlan, EvalScore, EvalSpec, Params2 } from "../../@types/log";
import { DatasetDetailView } from "./DatasetDetailView";
import { ScorerDetailView } from "./ScorerDetailView";
import { SolversDetailView } from "./SolverDetailView";

import clsx from "clsx";
import { FC, ReactNode } from "react";
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

  const steps = plan?.steps;

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

  return (
    <div className={styles.container}>
      <div
        className={styles.grid}
        style={{
          gridTemplateColumns: `repeat(${taskColumns.length}, fit-content(50%))`,
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
    </div>
  );
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
