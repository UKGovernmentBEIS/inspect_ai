import { createRoot } from "react-dom/client";
import api from "./api/index";
import { Capabilities } from "./api/types";
import { App } from "./App";
import { AppErrorBoundary } from "./AppErrorBoundary";
import { initializeAppStore } from "./contexts/appStore";
import { LogProvider } from "./contexts/LogContext";
import { initializeLogsStore } from "./contexts/logsStore";
import { SampleProvider } from "./contexts/SampleContext";
import { ApplicationState } from "./types";
import { throttle } from "./utils/sync";
import { getVscodeApi } from "./utils/vscode";

// Read any state from the page itself
const vscode = getVscodeApi();
const resolvedApi = api;
let initialState = undefined;
let capabilities: Capabilities = {
  downloadFiles: true,
  webWorkers: true,
  streamSamples: !!resolvedApi.get_log_pending_samples,
  streamSampleData: !!resolvedApi.get_log_sample_data,
  nativeFind: !vscode,
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
    capabilities.downloadFiles = false;
    capabilities.webWorkers = false;
  }
}

initializeAppStore(capabilities, initialState?.app);
initializeLogsStore(resolvedApi, initialState?.logs);

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
  <AppErrorBoundary>
    <LogProvider initialState={initialState} api={api}>
      <SampleProvider initialState={initialState} api={api}>
        <App
          api={resolvedApi}
          applicationState={initialState}
          saveApplicationState={throttle((state) => {
            const vscode = getVscodeApi();
            if (vscode) {
              vscode.setState(filterState(state));
            }
          }, 1000)}
        />
      </SampleProvider>
    </LogProvider>
  </AppErrorBoundary>,
);

function filterState(state: ApplicationState) {
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
function filterLargeSample(state: ApplicationState) {
  if (!state || !state.selectedSample) {
    return state;
  }

  const estimatedTotalSize = estimateSize(state.selectedSample.messages);
  if (estimatedTotalSize > 400000) {
    const { selectedSample, ...filteredState } = state;
    return filteredState;
  } else {
    return state;
  }
}

// Filters the selectedlog if it is too large
function filterLargeLogSummary(state: ApplicationState) {
  if (!state || !state.log.selectedLogSummary) {
    return state;
  }

  const estimatedSize = estimateSize(
    state.log.selectedLogSummary.sampleSummaries,
  );
  if (estimatedSize > 400000) {
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
