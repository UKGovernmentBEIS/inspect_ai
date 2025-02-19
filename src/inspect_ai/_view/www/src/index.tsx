import { createRoot } from "react-dom/client";
import { App } from "./App";
import api from "./api/index";
import { ApplicationState, Capabilities } from "./types";
import { throttle } from "./utils/sync";
import { getVscodeApi } from "./utils/vscode";

// Read any state from the page itself
const vscode = getVscodeApi();
let initialState = undefined;
let capabilities: Capabilities = {
  downloadFiles: true,
  webWorkers: true,
};
if (vscode) {
  initialState = filterState(vscode.getState() as ApplicationState);

  // Determine the capabilities
  const extensionVersionEl = document.querySelector(
    'meta[name="inspect-extension:version"]',
  );
  const extensionVersion = extensionVersionEl
    ? extensionVersionEl.getAttribute("content")
    : undefined;

  if (!extensionVersion) {
    capabilities = { downloadFiles: false, webWorkers: false };
  }
}

const containerId = "app";
const container = document.getElementById(containerId);
if (!container) {
  console.error("Root container not found");
  throw new Error(
    `Expected a container element with Id '${containerId}' but no such container element was present.`,
  );
}

const root = createRoot(container as HTMLElement);
root.render(
  <App
    api={api}
    applicationState={initialState}
    saveApplicationState={throttle((state) => {
      const vscode = getVscodeApi();
      if (vscode) {
        vscode.setState(filterState(state));
      }
    }, 1000)}
    capabilities={capabilities}
    pollForLogs={false}
  />,
);

function filterState(state: ApplicationState) {
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
function filterLargeSample(state: ApplicationState) {
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
function filterLargeSelectedLog(state: ApplicationState) {
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
