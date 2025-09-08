// Main React App Component
export { App } from "./app/App";

// Client API - Main exports
export { default as api } from "./client/api/index";
export { clientApi } from "./client/api/client-api";
export { SampleSizeLimitedExceededError } from "./client/api/client-api";

// Client APIs
export { createViewServerApi } from "./client/api/api-view-server.ts";
export { default as simpleHttpApi } from "./client/api/api-http";
export { default as vscodeApi } from "./client/api/api-vscode";

// Client API - Shared utilities
export * from "./client/api/api-shared";

// Client API - Types
export type {
  ClientAPI,
  LogViewAPI,
  Capabilities,
  EvalSummary,
  LogContents,
  LogFiles,
  LogFile,
  LogOverview,
  PendingSampleResponse,
  SampleDataResponse,
  PendingSamples,
  SampleData,
  EventData,
  AttachmentData,
  SampleSummary,
  HostMessage,
  RunningMetric,
} from "./client/api/types";

// Store and State Management (needed for App)
export { initializeStore, useStore, storeImplementation } from "./state/store";
export type { StoreState } from "./state/store";

// Log types
export type * as LogType from "./@types/log";
