import { Scores } from "../@types/log";
import { MetricSummary, ScoreSummary } from "./types";

export const metricDisplayName = (metric: MetricSummary): string => {
  let modifier = undefined;
  for (const metricModifier of metricModifiers) {
    modifier = metricModifier(metric);
    if (modifier) {
      break;
    }
  }
  const metricName = !modifier ? metric.name : `${metric.name}[${modifier}]`;

  return metricName;
};

type MetricModifier = (metric: MetricSummary) => string | undefined;

const clusterMetricModifier: MetricModifier = (
  metric: MetricSummary,
): string | undefined => {
  if (metric.name !== "stderr") {
    return undefined;
  }

  const clusterValue = ((metric.params || {}) as Record<string, unknown>)[
    "cluster"
  ];
  if (clusterValue === undefined || typeof clusterValue !== "string") {
    return undefined;
  }
  return clusterValue;
};

const metricModifiers: MetricModifier[] = [clusterMetricModifier];

export const toDisplayScorers = (scores?: Scores): ScoreSummary[] => {
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
