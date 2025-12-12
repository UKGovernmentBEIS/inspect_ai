import { LogDetails } from "../../client/api/types";

/**
 * Detects all unique scorer names and their types from sample summaries.
 * Used by the samples grid to detect scorer columns from individual samples.
 *
 * @param logDetails - Record of log details keyed by log file name
 * @returns Record mapping scorer names to their value types
 */
export const detectScorersFromSamples = (
  logDetails: Record<string, LogDetails>,
): Record<string, string> => {
  const scoreTypes: Record<string, string> = {};

  for (const details of Object.values(logDetails)) {
    for (const sample of details.sampleSummaries) {
      if (sample.scores) {
        for (const [name, score] of Object.entries(sample.scores)) {
          scoreTypes[name] = typeof score.value;
        }
      }
    }
  }

  return scoreTypes;
};

/**
 * Detects all unique scorer names and their types from log results.
 * Used by the logs grid to detect scorer columns from evaluation results.
 *
 * @param logDetails - Record of log details keyed by log file name
 * @returns Record mapping scorer names to their value types
 */
export const detectScorersFromResults = (
  logDetails: Record<string, LogDetails>,
): Record<string, string> => {
  const scoreTypes: Record<string, string> = {};

  for (const details of Object.values(logDetails)) {
    if (details.results?.scores) {
      // scores is an array of EvalScore objects
      for (const evalScore of details.results.scores) {
        // Each EvalScore has metrics which is a record of EvalMetric
        if (evalScore.metrics) {
          for (const [metricName, metric] of Object.entries(
            evalScore.metrics,
          )) {
            scoreTypes[metricName] = typeof metric.value;
          }
        }
      }
    }
  }

  return scoreTypes;
};
