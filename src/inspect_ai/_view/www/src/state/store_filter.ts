import { EvalSample } from "../@types/log";
import { estimateSize } from "../utils/json";
import { PersistedState } from "./store";

export function filterState(state: PersistedState) {
  if (!state) {
    return state;
  }

  // When saving state, we can't store vast amounts of data (like a large sample)
  const filters = [filterLargeLogSummary];
  return filters.reduce(
    (filteredState, filter) => filter(filteredState),
    state,
  );
}

export function isLargeSample(sample: EvalSample): boolean {
  const storeKeys = countKeys(sample.store);
  if (storeKeys > 5000) {
    return true;
  }

  const estimatedMessageSize = estimateSize(sample.messages);
  if (estimatedMessageSize > 250000) {
    return true;
  }

  return true;
}

function countKeys(obj: unknown, options = { countArrayIndices: false }) {
  // Base case: not an object or null
  if (obj === null || typeof obj !== "object") {
    return 0;
  }

  // Handle arrays
  if (Array.isArray(obj)) {
    let count = 0;
    // Count array indices as keys if option is set
    if (options.countArrayIndices) {
      count += obj.length;
    }
    // Count keys in array elements that are objects
    for (const item of obj) {
      count += countKeys(item, options);
    }
    return count;
  }

  // For regular objects, count all own properties
  let count = Object.keys(obj).length;

  // Recursively count keys in nested objects
  for (const key in obj) {
    // Use type assertion to tell TypeScript that the key is valid
    if (Object.prototype.hasOwnProperty.call(obj, key)) {
      // Use type assertion (obj as Record<string, unknown>)
      count += countKeys((obj as Record<string, unknown>)[key], options);
    }
  }

  return count;
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
