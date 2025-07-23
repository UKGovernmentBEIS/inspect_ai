import clsx from "clsx";
import { FC } from "react";
import { RunningMetric } from "../../../client/api/types";
import { LinkButton } from "../../../components/LinkButton";
import { Modal } from "../../../components/Modal";
import { metricDisplayName } from "../../../scoring/metrics";
import { groupScorers } from "../../../scoring/scores";
import { MetricSummary, ScoreSummary } from "../../../scoring/types";
import { useProperty } from "../../../state/hooks";
import { formatPrettyDecimal } from "../../../utils/format";
import styles from "./ResultsPanel.module.css";
import { ScoreGrid } from "./ScoreGrid";
import { UnscoredSamples } from "./UnscoredSamplesView";

const kMaxPrimaryScoreRows = 4;

export const displayScorersFromRunningMetrics = (metrics?: RunningMetric[]) => {
  if (!metrics) {
    return [];
  }

  const getKey = (metric: RunningMetric) => {
    return metric.reducer
      ? `${metric.scorer}-${metric.reducer}`
      : metric.scorer;
  };

  const scorers: Record<string, ScoreSummary> = {};
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

interface ResultsPanelProps {
  scorers?: ScoreSummary[];
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
    const unscoredSamples = scorers[0].unscoredSamples || 0;
    const scoredSamples = scorers[0].scoredSamples || 0;
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
              unscoredSamples={unscoredSamples}
              scoredSamples={scoredSamples}
            />
          );
        })}
      </div>
    );
  } else {
    const showReducer = scorers.findIndex((score) => !!score.reducer) !== -1;
    const grouped = groupScorers(scorers);

    // If grouping produced an empty array, no results to show
    if (grouped.length < 1) {
      return undefined;
    }

    // Try to select metrics with a group size 5 or less, if possible
    let primaryResults = grouped[0];

    // If there are no primary results, nothing to show here
    if (!primaryResults) {
      return undefined;
    }

    let showMore = grouped.length > 1;
    if (primaryResults.length > kMaxPrimaryScoreRows) {
      const shorterResults = grouped.find((g) => {
        return g.length <= kMaxPrimaryScoreRows;
      });
      if (shorterResults) {
        primaryResults = shorterResults;
      }

      // If the primary metrics are still too long, truncate them and
      // show the rest in the modal
      if (primaryResults.length > kMaxPrimaryScoreRows) {
        primaryResults = primaryResults.slice(0, kMaxPrimaryScoreRows);
        showMore = true;
      }
    }

    return (
      <div className={clsx(styles.metricsSummary)}>
        <ScoreGrid scoreGroups={[primaryResults]} showReducer={showReducer} />
        {showMore ? (
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

interface VerticalMetricProps {
  metric: MetricSummary;
  reducer?: string;
  isFirst: boolean;
  showReducer: boolean;
  unscoredSamples: number;
  scoredSamples: number;
}

/** Renders a Vertical Metric
 */
const VerticalMetric: FC<VerticalMetricProps> = ({
  metric,
  reducer,
  isFirst,
  showReducer,
  scoredSamples,
  unscoredSamples,
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
        <UnscoredSamples
          scoredSamples={scoredSamples}
          unscoredSamples={unscoredSamples}
        />
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
