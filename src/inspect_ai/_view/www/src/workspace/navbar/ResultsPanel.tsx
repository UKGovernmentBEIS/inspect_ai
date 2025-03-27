import clsx from "clsx";
import { FC } from "react";
import { RunningMetric } from "../../api/types";
import { ApplicationIcons } from "../../appearance/icons";
import { LinkButton } from "../../components/LinkButton";
import { Modal } from "../../components/Modal";
import { useProperty } from "../../state/hooks";
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

    return (
      <div className={clsx(styles.metricsSummary)}>
        <ScoreGrid scorers={grouped[0]} showReducer={showReducer} />
        {grouped.length > 1 ? (
          <>
            <Modal
              id="results-metrics"
              showing={showing}
              setShowing={setShowing}
              title={"Scoring Detail"}
            >
              {grouped.map((g) => {
                return <ScoreGrid scorers={g} showReducer={showReducer} />;
              })}
            </Modal>
          </>
        ) : undefined}
        <LinkButton
          className={styles.moreButton}
          text={"Additional metrics"}
          icon={ApplicationIcons.metrics}
          onClick={() => {
            setShowing(true);
          }}
        />
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
    const key = metricsKey(scorer.metrics);
    results[key] = results[key] || [];
    results[key].push(scorer);
  });
  return Object.values(results);
};

interface ScoreGridProps {
  scorers: ResultsScorer[];
  showReducer?: boolean;
}

const ScoreGrid: FC<ScoreGridProps> = ({ scorers, showReducer }) => {
  const metricCount = scorers[0].metrics.length;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${metricCount + 1}, max-content)`,
        columnGap: "0.5em",
        marginRight: "1em",
      }}
      className={clsx("text-size-small")}
    >
      <div></div>
      {scorers[0].metrics.map((m) => {
        return (
          <div className={clsx("text-style-label", "text-style-secondary")}>
            {m.name}
          </div>
        );
      })}

      {scorers.map((scorer) => {
        const results = [
          <div>
            {scorer.scorer}{" "}
            {showReducer && scorer.reducer ? `(${scorer.reducer})` : undefined}
          </div>,
        ];
        const metrics = scorer.metrics;
        metrics.forEach((m) => {
          results.push(
            <div style={{ justifySelf: "center", fontWeight: "600" }}>
              {formatPrettyDecimal(m.value)}
            </div>,
          );
        });
        return results;
      })}
    </div>
  );
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
  const titleFontClz = "text-size-small";
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
        {scorer.scorer} {showReducer ? `(${scorer.reducer || "default"})` : ""}
      </div>
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
