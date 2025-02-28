import {
  EvalLogHeader,
  EvalSummary,
  LogFiles,
  PendingSamples,
  SampleSummary,
} from "./api/types";
import { ContentImage, ContentText, EvalSample, Events } from "./types/log";

export interface AppState {
  status: AppStatus;
  offcanvas: boolean;
  showFind: boolean;
}

export interface LogsState {
  logs: LogFiles;
  logHeaders: Record<string, EvalLogHeader>;
  headersLoading: boolean;
  selectedLogIndex: number;
}

export interface LogState {
  selectedLogSummary?: EvalSummary;
  pendingSampleSummaries?: PendingSamples;
  selectedSampleIndex: number;
  filter: ScoreFilter;
  epoch: string;
  sort: string;
  score?: ScoreLabel;
}

export interface SampleState {
  selectedSample: EvalSample | undefined;
  sampleStatus: "loading" | "ok" | "error";
  sampleError: Error | undefined;
  runningSampleData: RunningSampleData | undefined;
}

export interface ApplicationState {
  logs: LogsState;
  log: LogState;
  sample: SampleState;

  selectedWorkspaceTab?: string;
  workspaceTabScrollPosition?: Record<string, number>;

  // Sample Context
  selectedSampleIndex?: number;
  selectedSample?: EvalSample;
  sampleStatus?: "loading" | "ok" | "error";
  sampleError?: Error;
  selectedSampleTab?: string;
  sampleScrollPosition?: number;
  showingSampleDialog?: boolean;

  // App Context
  app: AppState;
}

export interface AppStatus {
  loading: boolean;
  error?: Error;
}

export interface CurrentLog {
  name: string;
  contents: EvalSummary;
}

export interface Logs {
  log_dir: string;
  files: string[];
}

export interface ScoreLabel {
  name: string;
  scorer: string;
}

export interface ScoreFilter {
  value?: string;
}

export type SampleMode = "none" | "single" | "many";

export interface ContentTool {
  type: "tool";
  content: (ContentImage | ContentText)[];
}

export interface RunningSampleData {
  events: Events;
  summary: SampleSummary;
}
