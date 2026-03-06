import { EvalResults, Scores } from "../@types/log";
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

export const firstMetric = (results: EvalResults) => {
  const scores = results.scores || [];
  const firstScore = scores.length > 0 ? results.scores?.[0] : undefined;
  if (firstScore === undefined || firstScore.metrics === undefined) {
    return undefined;
  }

  const metrics = firstScore.metrics;
  if (Object.keys(metrics).length === 0) {
    return undefined;
  }

  const metric = metrics[Object.keys(metrics)[0]];
  if (metric === undefined) {
    return undefined;
  }
  return metric;
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

const groupMetricModifier: MetricModifier = (metric: MetricSummary) => {
  const groupKey = ((metric.params || {}) as Record<string, unknown>)[
    "group_key"
  ];
  if (groupKey === undefined || typeof groupKey !== "string") {
    return undefined;
  }
  const metricRaw = ((metric.params || {}) as Record<string, unknown>)[
    "metric"
  ];
  if (metricRaw === undefined || typeof metricRaw !== "object") {
    return undefined;
  }
  const metricObj = metricRaw as Record<string, unknown>;
  const name = metricObj["name"] as string;
  return name;
};

const metricModifiers: MetricModifier[] = [
  clusterMetricModifier,
  groupMetricModifier,
];

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
      unscoredSamples:
        score.unscored_samples !== null
          ? (score.unscored_samples as number)
          : undefined,
      scoredSamples:
        score.scored_samples !== null
          ? (score.scored_samples as number)
          : undefined,
    };
  });
};

const isGroupedMetric = (metric: MetricSummary): boolean => {
  if (!metric.params) {
    return false;
  }
  const params = metric.params as Record<string, unknown>;
  return params["group_key"] !== undefined && params["metric"] !== undefined;
};

const getBaseMetricName = (metric: MetricSummary): string | undefined => {
  if (!metric.params) {
    return undefined;
  }
  const params = metric.params as Record<string, unknown>;
  const metricObj = params["metric"] as Record<string, unknown> | undefined;
  if (!metricObj || typeof metricObj !== "object") {
    return undefined;
  }
  return metricObj["name"] as string;
};

const normalizeMetricName = (name: string): string => {
  return name.replace(/\d+$/, "");
};

export const expandGroupedMetrics = (
  scorers: ScoreSummary[],
): ScoreSummary[] => {
  const result: ScoreSummary[] = [];

  for (const scorer of scorers) {
    if (scorer.metrics.length === 0) {
      result.push(scorer);
      continue;
    }

    const hasGroupedMetrics = scorer.metrics.some(isGroupedMetric);

    if (!hasGroupedMetrics) {
      result.push(scorer);
      continue;
    }

    const metricsByBase = new Map<string, MetricSummary[]>();
    const nonGroupedMetrics: MetricSummary[] = [];

    for (const metric of scorer.metrics) {
      const baseMetricName = getBaseMetricName(metric);
      if (!baseMetricName) {
        nonGroupedMetrics.push(metric);
        continue;
      }

      if (!metricsByBase.has(baseMetricName)) {
        metricsByBase.set(baseMetricName, []);
      }
      metricsByBase.get(baseMetricName)!.push({
        ...metric,
        name: normalizeMetricName(metric.name),
      });
    }

    if (nonGroupedMetrics.length > 0) {
      result.push({
        scorer: scorer.scorer,
        reducer: scorer.reducer,
        metrics: nonGroupedMetrics,
        unscoredSamples: scorer.unscoredSamples,
        scoredSamples: scorer.scoredSamples,
      });
    }

    for (const [baseMetricName, metrics] of metricsByBase.entries()) {
      result.push({
        scorer: scorer.scorer,
        reducer: baseMetricName,
        metrics: metrics,
        unscoredSamples: scorer.unscoredSamples,
        scoredSamples: scorer.scoredSamples,
      });
    }
  }

  return result;
};
