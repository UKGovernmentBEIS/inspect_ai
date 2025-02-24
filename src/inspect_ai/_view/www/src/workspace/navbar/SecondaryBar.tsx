import clsx from "clsx";
import { SampleSummary } from "../../api/types";
import { ExpandablePanel } from "../../components/ExpandablePanel";
import { LabeledValue } from "../../components/LabeledValue";
import { EvalDescriptor } from "../../samples/descriptor/types";
import { scoreFilterItems } from "../../samples/sample-tools/filters";
import {
  EvalDataset,
  EvalPlan,
  EvalResults,
  EvalSpec,
  EvalStats,
} from "../../types/log";
import { formatDataset, formatDuration } from "../../utils/format";
import styles from "./SecondaryBar.module.css";

interface SecondaryBarProps {
  evalSpec?: EvalSpec;
  evalPlan?: EvalPlan;
  evalResults?: EvalResults;
  evalStats?: EvalStats;
  evalDescriptor?: EvalDescriptor;
  samples?: SampleSummary[];
  status?: string;
}

/**
 * Renders the SecondaryBar
 */
export const SecondaryBar: React.FC<SecondaryBarProps> = ({
  evalSpec,
  evalPlan,
  evalResults,
  evalStats,
  samples,
  evalDescriptor,
  status,
}) => {
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
        className={(styles.staticCol, "text-size-small")}
      >
        <DatasetSummary
          dataset={evalSpec.dataset}
          samples={samples}
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
      className={clsx(styles.container, "text-size-small")}
      collapse={true}
      lines={4}
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
  samples?: SampleSummary[];
  epochs: number;
}

/**
 * A component that displays the dataset
 */
const DatasetSummary: React.FC<DatasetSummaryProps> = ({
  dataset,
  samples,
  epochs,
}) => {
  if (!dataset) {
    return null;
  }

  return (
    <div>
      {samples?.length
        ? formatDataset(samples.length, epochs, dataset.name)
        : ""}
    </div>
  );
};

interface ScoreSummaryProps {
  evalDescriptor?: EvalDescriptor;
}

/**
 * A component that displays a list of scrorers
 */
const ScorerSummary: React.FC<ScoreSummaryProps> = ({ evalDescriptor }) => {
  if (!evalDescriptor) {
    return null;
  }

  const items = scoreFilterItems(evalDescriptor);
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
const ParamSummary: React.FC<ParamSummaryProps> = ({ params }) => {
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
