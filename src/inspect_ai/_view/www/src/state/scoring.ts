import { ScoreLabel } from "../app/types";
import { LogDetails, SampleSummary } from "../client/api/types";

/**
 * Extracts scorer information from sample summaries
 */
const getScorersFromSamples = (samples: SampleSummary[]): ScoreLabel[] => {
  // Collect unique score labels from all samples (scored)
  const scoreLabelsMap = new Map<string, ScoreLabel>();

  // Go through each sample and the scorers applied to it.
  // For dictionaries, use their keys.
  for (const sample of samples) {
    if (!sample.error && sample.scores) {
      for (const [scorerKey, scoreValue] of Object.entries(sample.scores)) {
        if (
          scoreValue.value &&
          typeof scoreValue.value === "object" &&
          !Array.isArray(scoreValue.value)
        ) {
          // If it's a dictionary, extract keys from within the value
          const valueDict = scoreValue.value as Record<string, unknown>;
          for (const innerKey of Object.keys(valueDict)) {
            const label = `${scorerKey}:${innerKey}`;
            if (!scoreLabelsMap.has(label)) {
              scoreLabelsMap.set(label, {
                name: innerKey,
                scorer: scorerKey,
              });
            }
          }
        } else {
          // If it's a simple value, use the scorer key directly
          if (!scoreLabelsMap.has(scorerKey)) {
            scoreLabelsMap.set(scorerKey, {
              name: scorerKey,
              scorer: scorerKey,
            });
          }
        }
      }
    }
  }

  return Array.from(scoreLabelsMap.values());
};

/**
 * Gets all available scorers for a log, prioritizing results over samples
 */
export const getAvailableScorers = (
  _log: LogDetails,
  sampleSummaries: SampleSummary[],
): ScoreLabel[] | undefined => {
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
  log: LogDetails,
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
