import { PersistedState } from "./store";

export function filterState(state: PersistedState) {
  if (!state) {
    return state;
  }

  // When saving state, we can't store vast amounts of data (like a large sample)
  const filters = [filterLargeSample, filterLargeLogSummary];
  return filters.reduce(
    (filteredState, filter) => filter(filteredState),
    state,
  );
}

// Filters the selected Sample if it is large
function filterLargeSample(state: PersistedState): PersistedState {
  if (!state || !state.sample || !state.sample.selectedSample) {
    return state;
  }

  const estimatedTotalSize = estimateSize(state.sample.selectedSample.messages);
  if (estimatedTotalSize > 250000) {
    return {
      ...state,
      sample: {
        ...state.sample,
        selectedSample: undefined,
      },
    };
  } else {
    return state;
  }
}

// Filters the selectedlog if it is too large
function filterLargeLogSummary(state: PersistedState): PersistedState {
  if (!state || !state.log || !state.log.selectedLogSummary) {
    return state;
  }

  const estimatedSize = estimateSize(
    state.log.selectedLogSummary.sampleSummaries,
  );
  if (estimatedSize > 250000) {
    return {
      ...state,
      log: {
        ...state.log,
        selectedLogSummary: undefined,
      },
    };
  } else {
    return state;
  }
}

function estimateSize(list: unknown[], frequency = 0.2) {
  if (!list || list.length === 0) {
    return 0;
  }

  // Total number of samples
  const sampleSize = Math.ceil(list.length * frequency);

  // Get a proper random sample without duplicates
  const messageIndices = new Set<number>();
  while (
    messageIndices.size < sampleSize &&
    messageIndices.size < list.length
  ) {
    const randomIndex = Math.floor(Math.random() * list.length);
    messageIndices.add(randomIndex);
  }

  // Calculate size from sampled messages
  const totalSize = Array.from(messageIndices).reduce((size, index) => {
    return size + JSON.stringify(list[index]).length;
  }, 0);

  // Estimate total size based on sample
  const estimatedTotalSize = (totalSize / sampleSize) * list.length;
  return estimatedTotalSize;
}
