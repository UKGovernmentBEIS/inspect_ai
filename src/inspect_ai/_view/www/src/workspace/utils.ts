import { EvalMetric } from "../types/log";

export const metricDisplayName = (metric: EvalMetric): string => {
  const metricParamNames = Object.keys(metric.params || {});
  const metricsParams =
    metricParamNames.length === 1
      ? metricParamNames[0]
      : `${metricParamNames[0]}, ...`;

  const metricName =
    metricParamNames.length === 0
      ? metric.name
      : `${metric.name} (${metricsParams})`;

  return metricName;
};
