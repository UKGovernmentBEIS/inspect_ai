import { EvalResults } from "../@types/log";
import { EvalSummary, SampleSummary } from "../client/api/types";

export interface ScorerInfo {
  name: string;
  scorer: string;
}

/**
 * Extracts scorer information from evaluation results
 */
const getScorersFromResults = (results?: EvalResults): ScorerInfo[] => {
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
  }, [] as ScorerInfo[]);
};

/**
 * Extracts scorer information from sample summaries
 */
const getScorersFromSamples = (samples: SampleSummary[]): ScorerInfo[] => {
  // Find a sample with scores
  const scoredSample = samples.find((sample) => {
    return !!sample.scores;
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
  log: EvalSummary,
  sampleSummaries: SampleSummary[],
): ScorerInfo[] | undefined => {
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
  log: EvalSummary,
  sampleSummaries: SampleSummary[],
): ScorerInfo | undefined => {
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
