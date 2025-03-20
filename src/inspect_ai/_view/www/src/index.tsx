import { createRoot } from "react-dom/client";
import api from "./api/index";
import { Capabilities } from "./api/types";
import { App } from "./App";
import { AppErrorBoundary } from "./AppErrorBoundary";
import { initializeStore } from "./state/store";
import storage from "./storage";
import { getVscodeApi } from "./utils/vscode";

// Resolve the api
const applicationApi = api;
const applicationStorage = storage;

// Application capabilities
const vscode = getVscodeApi();
let capabilities: Capabilities = {
  downloadFiles: true,
  webWorkers: true,
  streamSamples: !!applicationApi.get_log_pending_samples,
  streamSampleData: !!applicationApi.get_log_sample_data,
  nativeFind: !vscode,
};

// Initial state / storage
if (vscode) {
  // Adjust capabilities
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

// Inititialize the application store
initializeStore(applicationApi, capabilities, applicationStorage);

// Find the root element and render into it
const containerId = "app";
const container = document.getElementById(containerId);
if (!container) {
  console.error("Root container not found");
  throw new Error(
    `Expected a container element with Id '${containerId}' but no such container element was present.`,
  );
}

// Render into the root
const root = createRoot(container as HTMLElement);
root.render(
  <AppErrorBoundary>
    <App api={applicationApi} />
  </AppErrorBoundary>,
);
