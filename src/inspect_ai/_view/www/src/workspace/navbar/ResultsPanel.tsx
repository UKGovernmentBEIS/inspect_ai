import clsx from "clsx";
import { FC } from "react";
import { RunningMetric } from "../../api/types";
import { Scores } from "../../types/log";
import { formatPrettyDecimal } from "../../utils/format";
import { metricDisplayName } from "../utils";
import styles from "./ResultsPanel.module.css";

export interface ResultsMetric {
  name: string;
  params?: {};
  value: number;
}

export interface ResultsScorer {
  scorer: string;
  reducer?: string;
  metrics: ResultsMetric[];
}

export const displayScorersFromRunningMetrics = (metrics?: RunningMetric[]) => {
  if (!metrics) {
    return [];
  }

  const getKey = (metric: RunningMetric) => {
    return metric.reducer
      ? `${metric.scorer}-${metric.reducer}`
      : metric.scorer;
  };

  const scorers: Record<string, ResultsScorer> = {};
  metrics.forEach((metric) => {
    if (metric.value !== undefined) {
      const key = getKey(metric);
      if (!!scorers[key]) {
        scorers[key].metrics.push({
          name: metric.name,
          value: metric.value,
        });
      } else {
        scorers[key] = {
          scorer: metric.scorer,
          reducer: metric.reducer,
          metrics: [
            {
              name: metric.name,
              value: metric.value,
            },
          ],
        };
      }
    }
  });

  return Object.values(scorers);
};

export const toDisplayScorers = (scores?: Scores): ResultsScorer[] => {
  if (!scores) {
    return [];
  }

  return scores.map((score) => {
    return {
      scorer: score.name,
      reducer: score.reducer === null ? undefined : score.reducer,
      metrics: Object.keys(score.metrics).map((key) => {
        const metric = score.metrics[key];
        return {
          name: metric.name,
          value: metric.value,
          params: metric.params,
        };
      }),
    };
  });
};

interface ResultsPanelProps {
  scorers?: ResultsScorer[];
}

export const ResultsPanel: React.FC<ResultsPanelProps> = ({ scorers }) => {
  if (!scorers || scorers.length === 0) {
    return undefined;
  }

  // Get the display scorers
  if (scorers.length === 1) {
    const showReducer = !!scorers[0].reducer;
    const metrics = scorers[0].metrics;
    return (
      <div className={styles.simpleMetricsRows}>
        {metrics.map((metric, i) => {
          if (metric.value) {
            return (
              <VerticalMetric
                key={`simple-metric-${i}`}
                reducer={scorers[0].reducer}
                metric={metric}
                isFirst={i === 0}
                showReducer={showReducer}
              />
            );
          } else {
            return undefined;
          }
        })}
      </div>
    );
  } else {
    const showReducer = scorers.findIndex((score) => !!score.reducer) !== -1;
    return (
      <div className={styles.multiMetricsRows}>
        {scorers.map((scorer, index) => {
          return (
            <MultiScorerMetric
              key={`multi-metric-${index}`}
              scorer={scorer}
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
  metric: ResultsMetric;
  reducer?: string;
  isFirst: boolean;
  showReducer: boolean;
}

/** Renders a Vertical Metric
 */
const VerticalMetric: FC<VerticalMetricProps> = ({
  metric,
  reducer,
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
        {metricDisplayName(metric)}
      </div>
      {showReducer ? (
        <div
          className={clsx(
            "text-style-label",
            "text-style-secondary",
            styles.verticalMetricReducer,
          )}
        >
          {reducer || "default"}
        </div>
      ) : undefined}

      <div
        className={clsx(
          "vertical-metric-value",
          "text-size-largest",
          styles.verticalMetricValue,
        )}
      >
        {metric.value ? formatPrettyDecimal(metric.value) : undefined}
      </div>
    </div>
  );
};

interface MultiScorerMetricProps {
  scorer: ResultsScorer;
  isFirst: boolean;
  showReducer: boolean;
}

const MultiScorerMetric: FC<MultiScorerMetricProps> = ({
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
        {scorer.scorer}
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
        {scorer.metrics.map((metric) => {
          return (
            <div className={styles.multiScoreMetricGrid} key={metric.name}>
              <div>{metricDisplayName(metric)}</div>
              <div className={styles.multiScorerValueContent}>
                {metric.value ? formatPrettyDecimal(metric.value) : undefined}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
