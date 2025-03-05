import { useMemo } from "react";
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
import { mergeSampleSummaries } from "./utils";

// Fetches all samples summaries (both completed and incomplete)
// without applying any filtering
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

// Counts the total number of unfiltered sample summaries (both complete and incomplete)
export const useTotalSampleCount = () => {
  const sampleSummaries = useSampleSummaries();
  return useMemo(() => {
    return sampleSummaries.length;
  }, [sampleSummaries]);
};

// Provides the currently selected score for this eval, providing a default
// based upon the configuration (eval + summaries) if no scorer has been
// selected
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

// Provides the list of available scorers. Will inspect the eval or samples
// to determine scores (even for in progress evals that don't yet have final
// metrics)
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

// Provides the eval descriptor
export const useEvalDescriptor = () => {
  const scores = useScores();
  const sampleSummaries = useSampleSummaries();
  return useMemo(() => {
    return scores ? createEvalDescriptor(scores, sampleSummaries) : null;
  }, [scores, sampleSummaries]);
};

// Provides the sampls descriptor
export const useSampleDescriptor = () => {
  const evalDescriptor = useEvalDescriptor();
  const sampleSummaries = useSampleSummaries();
  const score = useScore();
  return useMemo(() => {
    return evalDescriptor
      ? createSamplesDescriptor(sampleSummaries, evalDescriptor, score)
      : undefined;
  }, [evalDescriptor, sampleSummaries, score]);
};

// Provides the list of filtered samples
// (applying sorting, grouping, and filtering)
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

// Computes the group by to use given a particular sort
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

// Computes the ordering for groups based upon the sort
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

// Provides the currently selected sample summary
export const useSelectedSampleSummary = () => {
  const filteredSamples = useFilteredSamples();
  const selectedIndex = useStore((state) => state.log.selectedSampleIndex);
  return useMemo(() => {
    return filteredSamples[selectedIndex];
  }, [filteredSamples, selectedIndex]);
};

export const useSampleData = () => {
  const sampleStatus = useStore((state) => state.sample.sampleStatus);
  const sampleError = useStore((state) => state.sample.sampleError);
  const selectedSample = useStore((state) => state.sample.selectedSample);
  const runningSampleData = useStore((state) => state.sample.runningSampleData);
  const loadSample = useStore((state) => state.sampleActions.loadSample);
  return useMemo(() => {
    return {
      status: sampleStatus,
      error: sampleError,
      sample: selectedSample,
      running: runningSampleData,
      loadSample,
    };
  }, [
    sampleStatus,
    sampleError,
    selectedSample,
    runningSampleData,
    loadSample,
  ]);
};

export const useLogSelection = () => {
  const selectedSampleSummary = useSelectedSampleSummary();
  const selectedLogFile = useStore((state) =>
    state.logsActions.getSelectedLogFile(),
  );

  return useMemo(() => {
    return {
      logFile: selectedLogFile,
      sample: selectedSampleSummary,
    };
  }, [selectedLogFile, selectedSampleSummary]);
};
