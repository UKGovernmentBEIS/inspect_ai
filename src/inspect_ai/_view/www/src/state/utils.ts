import { SampleSummary } from "../client/api/types";

// Function to merge log samples with pending samples
export const mergeSampleSummaries = (
  logSamples: SampleSummary[],
  pendingSamples: SampleSummary[],
) => {
  // Create a map of existing sample IDs to avoid duplicates
  const existingSampleIds = new Set(
    logSamples.map((sample) => `${sample.id}-${sample.epoch}`),
  );

  // Filter out any pending samples that already exist in the log
  const uniquePendingSamples = pendingSamples
    .filter((sample) => !existingSampleIds.has(`${sample.id}-${sample.epoch}`))
    .map((sample) => {
      // Always mark pending items as incomplete to be sure we trigger polling
      return { ...sample, completed: false };
    });

  // Combine and return all samples
  return [...logSamples, ...uniquePendingSamples];
};
