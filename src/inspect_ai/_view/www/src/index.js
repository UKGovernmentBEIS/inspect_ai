import { render } from "preact";
import { html } from "htm/preact";

import { App } from "./App.mjs";
import api from "./api/index";
import { getVscodeApi } from "./utils/vscode";
import { throttle } from "./utils/sync.mjs";

// Read any state from the page itself
const vscode = getVscodeApi();
let initialState = undefined;
if (vscode) {
  initialState = filterState(vscode.getState());
}

render(
  html`<${App}
    api=${api}
    initialState=${initialState}
    saveInitialState=${throttle((state) => {
      const vscode = getVscodeApi();
      if (vscode) {
        vscode.setState(filterState(state));
      }
    }, 1000)}
  />`,
  document.getElementById("app"),
);

function filterState(state) {
  if (!state) {
    return state;
  }

  // When saving state, we can't store vast amounts of data (like a large sample)
  const filters = [filterLargeSample, filterLargeSelectedLog];
  return filters.reduce(
    (filteredState, filter) => filter(filteredState),
    state,
  );
}

// Filters the selected Sample if it is large
function filterLargeSample(state) {
  if (!state || !state.selectedSample) {
    return state;
  }

  const estimatedTotalSize = estimateSize(state.selectedSample.messages);
  if (estimatedTotalSize > 400000) {
    const { selectedSample, ...filteredState } = state; // eslint-disable-line
    return filteredState;
  } else {
    return state;
  }
}

// Filters the selectedlog if it is too large
function filterLargeSelectedLog(state) {
  if (!state || !state.selectedLog?.contents) {
    return state;
  }

  const estimatedSize = estimateSize(
    state.selectedLog.contents.sampleSummaries,
  );
  if (estimatedSize > 400000) {
    const { selectedLog, ...filteredState } = state; // eslint-disable-line
    return filteredState;
  } else {
    return state;
  }
}

function estimateSize(list, frequency = 0.2) {
  if (!list || list.len === 0) {
    return 0;
  }

  // Total number of samples
  const sampleSize = Math.ceil(list.length * frequency);

  // Get a proper random sample without duplicates
  const messageIndices = new Set();
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
