import clsx from "clsx";
import { FC } from "react";
import { Scores } from "../../../@types/log";
import { RunningMetric } from "../../../client/api/types";
import { LinkButton } from "../../../components/LinkButton";
import { Modal } from "../../../components/Modal";
import { useProperty } from "../../../state/hooks";
import { formatPrettyDecimal } from "../../../utils/format";
import { metricDisplayName } from "../utils";
import styles from "./ResultsPanel.module.css";
import { ScoreGrid } from "./ScoreGrid";

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
    if (metric.value !== undefined && metric.value !== null) {
      const key = getKey(metric);
      if (scorers[key]) {
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

export const ResultsPanel: FC<ResultsPanelProps> = ({ scorers }) => {
  const [showing, setShowing] = useProperty(
    "results-panel-metrics",
    "modal-showing",
    {
      defaultValue: false,
    },
  );

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
          return (
            <VerticalMetric
              key={`simple-metric-${i}`}
              reducer={scorers[0].reducer}
              metric={metric}
              isFirst={i === 0}
              showReducer={showReducer}
            />
          );
        })}
      </div>
    );
  } else {
    const showReducer = scorers.findIndex((score) => !!score.reducer) !== -1;
    const grouped = groupMetrics(scorers);

    // Try to select metrics with a group size 5 or less, if possible
    let primaryResults = grouped[0];
    if (primaryResults.length > 5) {
      const shorterResults = grouped.find((g) => {
        return g.length <= 5;
      });
      if (shorterResults) {
        primaryResults = shorterResults;
      }
    }

    return (
      <div className={clsx(styles.metricsSummary)}>
        <ScoreGrid scoreGroups={[primaryResults]} showReducer={showReducer} />
        {grouped.length > 1 ? (
          <>
            <Modal
              id="results-metrics"
              showing={showing}
              setShowing={setShowing}
              title={"Scoring Detail"}
            >
              <ScoreGrid
                scoreGroups={grouped}
                showReducer={showReducer}
                className={styles.modalScores}
                striped={false}
              />
            </Modal>
            <LinkButton
              className={styles.moreButton}
              text={"All scoring..."}
              onClick={() => {
                setShowing(true);
              }}
            />
          </>
        ) : undefined}
      </div>
    );
  }
};

const metricsKey = (metrics: ResultsMetric[]): string => {
  const metricKey = metrics.map((m) => m.name).join("");
  return metricKey;
};

const groupMetrics = (scorers: ResultsScorer[]): ResultsScorer[][] => {
  const results: Record<string, ResultsScorer[]> = {};
  scorers.forEach((scorer) => {
    if (scorer.metrics.length > 0) {
      const key = metricsKey(scorer.metrics);
      results[key] = results[key] || [];

      results[key].push(scorer);
    }
  });
  return Object.values(results);
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
        {metric.value !== undefined && metric.value !== null
          ? formatPrettyDecimal(metric.value)
          : "n/a"}
      </div>
    </div>
  );
};
