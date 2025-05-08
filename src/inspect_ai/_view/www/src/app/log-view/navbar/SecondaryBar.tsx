import clsx from "clsx";
import { FC } from "react";
import {
  EvalDataset,
  EvalPlan,
  EvalResults,
  EvalSpec,
  EvalStats,
} from "../../../@types/log";
import { EvalDescriptor } from "../../../app/samples/descriptor/types";
import { sampleFilterItems } from "../../../app/samples/sample-tools/filters";
import { ExpandablePanel } from "../../../components/ExpandablePanel";
import { LabeledValue } from "../../../components/LabeledValue";
import { useEvalDescriptor } from "../../../state/hooks";
import { formatDataset, formatDuration } from "../../../utils/format";
import styles from "./SecondaryBar.module.css";

interface SecondaryBarProps {
  evalSpec?: EvalSpec;
  evalPlan?: EvalPlan;
  evalResults?: EvalResults | null;
  evalStats?: EvalStats;
  status?: string;
  sampleCount?: number;
}

/**
 * Renders the SecondaryBar
 */
export const SecondaryBar: FC<SecondaryBarProps> = ({
  evalSpec,
  evalPlan,
  evalResults,
  evalStats,
  status,
  sampleCount,
}) => {
  const evalDescriptor = useEvalDescriptor();
  if (!evalSpec || status !== "success") {
    return null;
  }

  const epochs = evalSpec.config.epochs || 1;
  const hyperparameters: Record<string, unknown> = {
    ...(evalPlan?.config || {}),
    ...(evalSpec.task_args || {}),
  };

  const hasConfig = Object.keys(hyperparameters).length > 0;

  const values = [];
  values.push({
    size: "minmax(12%, auto)",
    value: (
      <LabeledValue
        key="sb-dataset"
        label="Dataset"
        className={clsx(styles.staticCol, "text-size-small")}
      >
        <DatasetSummary
          dataset={evalSpec.dataset}
          sampleCount={sampleCount}
          epochs={epochs}
        />
      </LabeledValue>
    ),
  });

  const label =
    evalResults?.scores && evalResults.scores.length > 1 ? "Scorers" : "Scorer";
  values.push({
    size: "minmax(12%, auto)",
    value: (
      <LabeledValue
        key="sb-scorer"
        label={label}
        className={clsx(
          styles.staticCol,
          hasConfig ? styles.justifyLeft : styles.justifyCenter,
          "text-size-small",
        )}
      >
        <ScorerSummary evalDescriptor={evalDescriptor} />
      </LabeledValue>
    ),
  });

  if (hasConfig) {
    values.push({
      size: "minmax(12%, auto)",
      value: (
        <LabeledValue
          key="sb-params"
          label="Config"
          className={clsx(styles.justifyRight, "text-size-small")}
        >
          <ParamSummary params={hyperparameters} />
        </LabeledValue>
      ),
    });
  }

  if (evalStats) {
    const totalDuration = formatDuration(
      new Date(evalStats?.started_at),
      new Date(evalStats?.completed_at),
    );
    values.push({
      size: "minmax(12%, auto)",
      value: (
        <LabeledValue
          key="sb-duration"
          label="Duration"
          className={clsx(styles.justifyRight, "text-size-small")}
        >
          {totalDuration}
        </LabeledValue>
      ),
    });
  }

  return (
    <ExpandablePanel
      id={"secondary-nav-bar"}
      className={clsx(styles.container, "text-size-small")}
      collapse={true}
      lines={5}
    >
      <div
        className={styles.valueGrid}
        style={{
          gridTemplateColumns: `${values
            .map((val) => {
              return val.size;
            })
            .join(" ")}`,
        }}
      >
        {values.map((val) => {
          return val.value;
        })}
      </div>
    </ExpandablePanel>
  );
};

interface DatasetSummaryProps {
  dataset?: EvalDataset;
  epochs: number;
  sampleCount?: number;
}

/**
 * A component that displays the dataset
 */
const DatasetSummary: FC<DatasetSummaryProps> = ({
  sampleCount,
  dataset,
  epochs,
}) => {
  if (!dataset) {
    return null;
  }

  return (
    <div>
      {sampleCount ? formatDataset(sampleCount, epochs, dataset.name) : ""}
    </div>
  );
};

interface ScoreSummaryProps {
  evalDescriptor?: EvalDescriptor | null;
}

/**
 * A component that displays a list of scrorers
 */
const ScorerSummary: FC<ScoreSummaryProps> = ({ evalDescriptor }) => {
  if (!evalDescriptor) {
    return null;
  }

  const items = sampleFilterItems(evalDescriptor);
  return (
    <span style={{ position: "relative" }}>
      {Array.from(items).map((item, index, array) => (
        <span key={index}>
          <span title={item.tooltip}>{item.canonicalName}</span>
          {index < array.length - 1 ? ", " : ""}
        </span>
      ))}
    </span>
  );
};

interface ParamSummaryProps {
  params: Record<string, unknown>;
}

/**
 * A component that displays a summary of parameters.
 */
const ParamSummary: FC<ParamSummaryProps> = ({ params }) => {
  if (!params) {
    return null;
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
    return (
      <code style={{ padding: 0, color: "var(--bs-body-color)" }}>
        {paraValues.join(", ")}
      </code>
    );
  } else {
    return null;
  }
};
