import { MetricSummary, ScoreSummary } from "./types";

export const groupScorers = (scorers: ScoreSummary[]): ScoreSummary[][] => {
  const results: Record<string, ScoreSummary[]> = {};
  scorers.forEach((scorer) => {
    if (scorer.metrics.length > 0) {
      const key = metricsKey(scorer.metrics);
      results[key] = results[key] || [];

      results[key].push(scorer);
    }
  });
  return Object.values(results);
};

const metricsKey = (metrics: MetricSummary[]): string => {
  const metricKey = metrics.map((m) => m.name).join("");
  return metricKey;
};
