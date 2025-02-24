import {
  EvalLogHeader,
  EvalSummary,
  LogFiles,
  SampleSummary,
} from "./api/types";
import { ContentImage, ContentText, EvalSample } from "./types/log";

// Define the state interface
export interface AppState {
  status: AppStatus;
  offcanvas: boolean;
  showFind: boolean;
}

export interface ApplicationState {
  // Logs Context
  logs?: LogFiles;
  logHeaders?: Record<string, EvalLogHeader>;
  headersLoading?: boolean;

  // Log Context
  selectedLogIndex?: number;
  selectedLogFile?: string;
  selectedLogSummary?: EvalSummary;
  filteredSamples?: SampleSummary[];
  filter?: ScoreFilter;
  epoch?: string;
  sort?: string;
  scores?: ScoreLabel[];
  score?: ScoreLabel;
  groupBy?: "none" | "epoch" | "sample";
  groupByOrder?: "asc" | "desc";
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
