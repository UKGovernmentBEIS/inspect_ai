// Main App Component
export { App } from "./app/App";

// Client API - Main exports
export { default as api } from "./client/api/index";
export { clientApi } from "./client/api/client-api";
export { SampleSizeLimitedExceededError } from "./client/api/client-api";

// Client API - Individual API implementations
export { default as browserApi } from "./client/api/api-browser";
export { default as simpleHttpApi } from "./client/api/api-http";
export { default as vscodeApi } from "./client/api/api-vscode";

// Client API - Shared utilities
export * from "./client/api/api-shared";
export * from "./client/api/jsonrpc";

// Client API - Types (comprehensive export)
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

// Remote file handling
export { openRemoteLogFile, SampleNotFoundError } from "./client/remote/remoteLogFile";
export { FileSizeLimitError } from "./client/remote/remoteZipFile";
export type { RemoteLogFile } from "./client/remote/remoteLogFile";

// Client storage
export { default as storage } from "./client/storage/index";

// Client utilities
export * from "./client/utils/type-utils";

// Store and State Management (needed for App)
export { initializeStore, useStore, storeImplementation } from "./state/store";
export type { StoreState } from "./state/store";

// Log types (from @types/log.d.ts)
export type {
  EvalLog,
  EvalSpec,
  EvalPlan,
  EvalResults,
  EvalStats,
  EvalSample,
  EvalError,
  EvalMetric,
  Model,
  Task,
  Target,
  Input,
  Scores1,
  Status,
  Version,
  TaskId,
  TaskVersion,
  RunId,
  EvalId,
  StartedAt,
  CompletedAt,
} from "./@types/log";
