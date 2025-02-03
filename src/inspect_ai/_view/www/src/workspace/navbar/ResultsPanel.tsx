import clsx from "clsx";
import { EvalMetric, EvalResults, EvalScore, Reducer } from "../../types/log";
import { formatPrettyDecimal } from "../../utils/format";
import styles from "./ResultsPanel.module.css";

interface ResultsPanelProps {
  results?: EvalResults;
}

interface MetricSummary {
  reducer: Reducer;
  metric: EvalMetric;
}

export const ResultsPanel: React.FC<ResultsPanelProps> = ({ results }) => {
  // Map the scores into a list of key/values
  if (results?.scores?.length === 1) {
    const scorers: Record<string, MetricSummary[]> = {};
    results.scores.map((score) => {
      scorers[score.name] = Object.keys(score.metrics).map((key) => {
        return {
          reducer: score.reducer,
          metric: {
            name: key,
            value: score.metrics[key].value,
            options: {},
            metadata: {},
          },
        };
      });
    });

    const metrics = Object.values(scorers)[0];
    return (
      <div className={styles.simpleMetricsRows}>
        {metrics.map((metric, i) => {
          return <VerticalMetric metricSummary={metric} isFirst={i === 0} />;
        })}
      </div>
    );
  } else {
    return (
      <div className={styles.multiMetricsRows}>
        {results?.scores?.map((score, index) => {
          return <MultiScorerMetric scorer={score} isFirst={index === 0} />;
        })}
      </div>
    );
  }
};

interface VerticalMetricProps {
  metricSummary: MetricSummary;
  isFirst: boolean;
}

/** Renders a Vertical Metric
 */
const VerticalMetric: React.FC<VerticalMetricProps> = ({
  metricSummary,
  isFirst,
}) => {
  const reducer_component = metricSummary.reducer ? (
    <div
      className={clsx(
        "text-style-label",
        "text-style-secondary",
        styles.verticalMetricReducer,
      )}
    >
      {metricSummary.reducer}
    </div>
  ) : (
    ""
  );

  return (
    <div style={{ paddingLeft: isFirst ? "0" : "1em" }}>
      <div
        className={clsx(
          "vertical-metric-label",
          "text-style-label",
          "text-style-secondary",
          styles.verticalMetricName,
        )}
      >
        {metricSummary.metric.name}
      </div>
      {reducer_component}
      <div
        className={clsx("vertical-metric-value", styles.verticalMetricValue)}
      >
        {formatPrettyDecimal(metricSummary.metric.value)}
      </div>
    </div>
  );
};

interface MultiScorerMetricProps {
  scorer: EvalScore;
  isFirst: boolean;
}

const MultiScorerMetric: React.FC<MultiScorerMetricProps> = ({
  scorer,
  isFirst,
}) => {
  const titleFontClz = "text-size-base";
  const reducerFontClz = "text-size-smaller";
  const valueFontClz = "text-size-base";

  const reducer_component = scorer.reducer ? (
    <div
      className={clsx(
        reducerFontClz,
        "text-style-label",
        "text-style-secondary",
        styles.multiScorerReducer,
      )}
    >
      {scorer.reducer}
    </div>
  ) : (
    ""
  );

  return (
    <div style={{ paddingLeft: isFirst ? "0" : "1.5em" }}>
      <div
        className={clsx(
          titleFontClz,
          "text-style-label",
          "text-style-secondary",
          "multi-score-label",
          styles.multiScorerLabel,
        )}
      >
        {scorer.name}
      </div>
      {reducer_component}
      <div className={clsx(valueFontClz, styles.multiScorerValue)}>
        {Object.keys(scorer.metrics).map((key) => {
          const metric = scorer.metrics[key];
          return (
            <div>
              <div>{metric.name}</div>
              <div className={styles.multiScorerValueContent}>
                {formatPrettyDecimal(metric.value)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
