import clsx from "clsx";
import { EvalMetric, EvalResults, EvalScore, Reducer } from "../../types/log";
import { formatPrettyDecimal } from "../../utils/format";
import { metricDisplayName } from "../utils";
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
            params: score.metrics[key].params,
            metadata: {},
          },
        };
      });
    });

    const metrics = Object.values(scorers)[0];
    const showReducer = !!metrics[0].reducer;
    return (
      <div className={styles.simpleMetricsRows}>
        {metrics.map((metric, i) => {
          return (
            <VerticalMetric
              key={`simple-metric-${i}`}
              metricSummary={metric}
              isFirst={i === 0}
              showReducer={showReducer}
            />
          );
        })}
      </div>
    );
  } else {
    const showReducer =
      results?.scores.findIndex((score) => !!score.reducer) !== -1;
    return (
      <div className={styles.multiMetricsRows}>
        {results?.scores?.map((score, index) => {
          return (
            <MultiScorerMetric
              key={`multi-metric-${index}`}
              scorer={score}
              isFirst={index === 0}
              showReducer={showReducer}
            />
          );
        })}
      </div>
    );
  }
};

interface VerticalMetricProps {
  metricSummary: MetricSummary;
  isFirst: boolean;
  showReducer: boolean;
}

/** Renders a Vertical Metric
 */
const VerticalMetric: React.FC<VerticalMetricProps> = ({
  metricSummary,
  isFirst,
  showReducer,
}) => {
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
        {metricDisplayName(metricSummary.metric)}
      </div>
      {showReducer ? (
        <div
          className={clsx(
            "text-style-label",
            "text-style-secondary",
            styles.verticalMetricReducer,
          )}
        >
          {metricSummary.reducer || "default"}
        </div>
      ) : undefined}

      <div
        className={clsx(
          "vertical-metric-value",
          "text-size-largest",
          styles.verticalMetricValue,
        )}
      >
        {formatPrettyDecimal(metricSummary.metric.value)}
      </div>
    </div>
  );
};

interface MultiScorerMetricProps {
  scorer: EvalScore;
  isFirst: boolean;
  showReducer: boolean;
}

const MultiScorerMetric: React.FC<MultiScorerMetricProps> = ({
  scorer,
  isFirst,
  showReducer,
}) => {
  const titleFontClz = "text-size-base";
  const reducerFontClz = "text-size-smaller";
  const valueFontClz = "text-size-base";

  return (
    <div
      className={clsx(
        styles.multiScorer,
        isFirst ? styles.multiScorerIndent : undefined,
      )}
    >
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
      {showReducer ? (
        <div
          className={clsx(
            reducerFontClz,
            "text-style-label",
            "text-style-secondary",
            styles.multiScorerReducer,
          )}
        >
          {scorer.reducer || "default"}
        </div>
      ) : undefined}
      <div className={clsx(valueFontClz, styles.multiScorerValue)}>
        {Object.keys(scorer.metrics).map((key) => {
          const metric = scorer.metrics[key];
          return (
            <div className={styles.multiScoreMetricGrid} key={key}>
              <div>{metricDisplayName(metric)}</div>
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
