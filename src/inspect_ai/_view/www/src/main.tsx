import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import api from "./client/api/index";
import { Capabilities } from "./client/api/types";
import storage from "./client/storage";
import { initializeStore, storeImplementation } from "./state/store";
import { getVscodeApi } from "./utils/vscode";

// Resolve the api
const applicationApi = api;
const applicationStorage = storage;

// Application capabilities
const vscode = getVscodeApi();
let capabilities: Capabilities = {
  downloadFiles: true,
  downloadLogs: !!applicationApi.download_log,
  webWorkers: true,
  streamSamples: !!applicationApi.get_log_pending_samples,
  streamSampleData: !!applicationApi.get_log_sample_data,
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

  capabilities.downloadFiles = false;
  if (!extensionVersion) {
    capabilities.webWorkers = false;
  }
}

// Inititialize the application store
initializeStore(applicationApi, capabilities, applicationStorage);

// Determine whether we need to restore a stored hash
restoreHash();

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
root.render(<App api={applicationApi} />);

function restoreHash() {
  // Check if we need to restore a route
  if (storeImplementation && storeImplementation.getState().app.urlHash) {
    const storedHash = storeImplementation.getState().app.urlHash;
    if (storedHash) {
      // Directly set the window location hash if there is
      // a stored hash that needs to be restored
      if (storedHash.startsWith("/")) {
        window.location.hash = storedHash;
      } else if (storedHash.startsWith("#")) {
        window.location.hash = storedHash;
      } else {
        window.location.hash = "#" + storedHash;
      }
    }
  }
}
