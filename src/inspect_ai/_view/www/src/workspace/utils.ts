import { EvalMetric } from "../types/log";

export const metricDisplayName = (metric: EvalMetric): string => {
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

type MetricModifier = (metric: EvalMetric) => string | undefined;

const clusterMetricModifier: MetricModifier = (
  metric: EvalMetric,
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
