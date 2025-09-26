import { EvalResults } from "../@types/log";
import { ScoreLabel } from "../app/types";
import { LogInfo, SampleSummary } from "../client/api/types";

/**
 * Extracts scorer information from evaluation results
 */
const getScorersFromResults = (results?: EvalResults): ScoreLabel[] => {
  if (!results?.scores) {
    return [];
  }

  return results.scores.reduce((uniqueScorers, score) => {
    const isDuplicate = uniqueScorers.some(
      (existing) =>
        existing.scorer === score.scorer && existing.name === score.name,
    );

    if (!isDuplicate) {
      uniqueScorers.push({
        name: score.name,
        scorer: score.scorer,
      });
    }

    return uniqueScorers;
  }, [] as ScoreLabel[]);
};

/**
 * Extracts scorer information from sample summaries
 */
const getScorersFromSamples = (samples: SampleSummary[]): ScoreLabel[] => {
  // Find a sample with scores
  const scoredSample = samples.find((sample) => {
    return !sample.error && sample.completed && !!sample.scores;
  });

  return Object.keys(scoredSample?.scores || {}).map((key) => ({
    name: key,
    scorer: key,
  }));
};

/**
 * Gets all available scorers for a log, prioritizing results over samples
 */
export const getAvailableScorers = (
  log: LogInfo,
  sampleSummaries: SampleSummary[],
): ScoreLabel[] | undefined => {
  const resultScorers = log.results ? getScorersFromResults(log.results) : [];
  if (resultScorers.length > 0) {
    return resultScorers;
  }

  const sampleScorers = getScorersFromSamples(sampleSummaries);
  if (sampleScorers.length > 0) {
    return sampleScorers;
  }

  return undefined;
};

/**
 * Gets the default scorer to use, preferring the first scorer from results
 * or falling back to the first scorer from samples
 */
export const getDefaultScorer = (
  log: LogInfo,
  sampleSummaries: SampleSummary[],
): ScoreLabel | undefined => {
  if (sampleSummaries.length === 0) {
    return undefined;
  }

  const allScorers = getAvailableScorers(log, sampleSummaries);
  if (allScorers) {
    return allScorers[0];
  } else {
    return undefined;
  }
};
