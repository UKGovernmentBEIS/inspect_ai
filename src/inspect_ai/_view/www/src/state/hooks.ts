import { useMemo } from "react";
import { SampleSummary } from "../api/types";
import { kEpochAscVal, kSampleAscVal, kScoreAscVal } from "../constants";
import {
  createEvalDescriptor,
  createSamplesDescriptor,
} from "../samples/descriptor/samplesDescriptor";
import { filterSamples } from "../samples/sample-tools/filters";
import {
  byEpoch,
  bySample,
  sortSamples,
} from "../samples/sample-tools/SortFilter";
import { getAvailableScorers, getDefaultScorer } from "../scoring/utils";
import { useStore } from "./store";

export const useSampleSummaries = () => {
  const selectedLogSummary = useStore((state) => state.log.selectedLogSummary);
  const pendingSampleSummaries = useStore(
    (state) => state.log.pendingSampleSummaries,
  );

  return useMemo(() => {
    return mergeSampleSummaries(
      selectedLogSummary?.sampleSummaries || [],
      pendingSampleSummaries?.samples || [],
    );
  }, [selectedLogSummary, pendingSampleSummaries]);
};

export const useTotalSampleCount = () => {
  const sampleSummaries = useSampleSummaries();
  return useMemo(() => {
    return sampleSummaries.length;
  }, [sampleSummaries]);
};

export const useScore = () => {
  const selectedLogSummary = useStore((state) => state.log.selectedLogSummary);
  const sampleSummaries = useSampleSummaries();
  const score = useStore((state) => state.log.score);
  return useMemo(() => {
    if (score) {
      return score;
    } else if (selectedLogSummary) {
      return getDefaultScorer(selectedLogSummary, sampleSummaries);
    } else {
      return undefined;
    }
  }, [selectedLogSummary, sampleSummaries, score]);
};

export const useScores = () => {
  const selectedLogSummary = useStore((state) => state.log.selectedLogSummary);
  const sampleSummaries = useSampleSummaries();
  return useMemo(() => {
    if (!selectedLogSummary) {
      return [];
    }

    return getAvailableScorers(selectedLogSummary, sampleSummaries) || [];
  }, [selectedLogSummary, sampleSummaries]);
};

export const useEvalDescriptor = () => {
  const scores = useScores();
  const sampleSummaries = useSampleSummaries();
  return useMemo(() => {
    return scores ? createEvalDescriptor(scores, sampleSummaries) : null;
  }, [scores, sampleSummaries]);
};

export const useSampleDescriptor = () => {
  const evalDescriptor = useEvalDescriptor();
  const sampleSummaries = useSampleSummaries();
  const score = useScore();
  return useMemo(() => {
    return evalDescriptor && score
      ? createSamplesDescriptor(sampleSummaries, evalDescriptor, score)
      : undefined;
  }, [evalDescriptor, sampleSummaries, score]);
};

export const useFilteredSamples = () => {
  const evalDescriptor = useEvalDescriptor();
  const sampleSummaries = useSampleSummaries();
  const filter = useStore((state) => state.log.filter);
  const epoch = useStore((state) => state.log.epoch);
  const sort = useStore((state) => state.log.sort);
  const samplesDescriptor = useSampleDescriptor();
  const score = useScore();

  return useMemo(() => {
    // Apply filters
    const prefiltered =
      evalDescriptor && filter.value
        ? filterSamples(evalDescriptor, sampleSummaries, filter.value).result
        : sampleSummaries;

    // Filter epochs
    const filtered =
      epoch && epoch !== "all"
        ? prefiltered.filter((sample) => epoch === String(sample.epoch))
        : prefiltered;

    // Sort samples
    const sorted = samplesDescriptor
      ? sortSamples(sort, filtered, samplesDescriptor, score)
      : filtered;

    return [...sorted];
  }, [
    evalDescriptor,
    sampleSummaries,
    filter,
    epoch,
    sort,
    samplesDescriptor,
    score,
  ]);
};

export const useGroupBy = () => {
  const selectedLogSummary = useStore((state) => state.log.selectedLogSummary);
  const sort = useStore((state) => state.log.sort);
  const epoch = useStore((state) => state.log.epoch);
  return useMemo(() => {
    const epochs = selectedLogSummary?.eval?.config?.epochs || 1;
    if (epochs > 1) {
      if (byEpoch(sort) || epoch !== "all") {
        return "epoch";
      } else if (bySample(sort)) {
        return "sample";
      }
    }

    return "none";
  }, [selectedLogSummary, sort, epoch]);
};

export const useGroupByOrder = () => {
  const sort = useStore((state) => state.log.sort);
  return useMemo(() => {
    return sort === kSampleAscVal ||
      sort === kEpochAscVal ||
      sort === kScoreAscVal
      ? "asc"
      : "desc";
  }, [sort]);
};

export const useSelectedSampleSummary = () => {
  const filteredSamples = useFilteredSamples();
  const selectedIndex = useStore((state) => state.log.selectedSampleIndex);
  return useMemo(() => {
    return filteredSamples[selectedIndex];
  }, [filteredSamples, selectedIndex]);
};

// Function to merge log samples with pending samples
const mergeSampleSummaries = (
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
