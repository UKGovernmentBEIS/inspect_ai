import {
  EvalLogHeader,
  EvalSummary,
  LogFiles,
  SampleSummary,
} from "./api/types";
import { ContentImage, ContentText, EvalSample } from "./types/log";

export interface ApplicationState {
  logs?: LogFiles;
  selectedLogIndex?: number;
  logHeaders?: Record<string, EvalLogHeader>;
  headersLoading?: boolean;
  selectedLog?: CurrentLog;
  selectedWorkspaceTab?: string;
  selectedSampleIndex?: number;
  selectedSample?: EvalSample;
  sampleStatus?: "loading" | "ok" | "error";
  sampleError?: Error;
  selectedSampleTab?: string;
  sampleScrollPosition?: number;
  showingSampleDialog?: boolean;
  status?: AppStatus;
  offcanvas?: boolean;
  showFind?: boolean;
  filter?: ScoreFilter;
  epoch?: string;
  sort?: string;
  scores?: ScoreLabel[];
  score?: ScoreLabel;
  filteredSamples?: SampleSummary[];
  groupBy?: "none" | "epoch" | "sample";
  groupByOrder?: "asc" | "desc";
  workspaceTabScrollPosition?: Record<string, number>;
}

export interface AppStatus {
  loading: boolean;
  error?: Error;
}

export interface Capabilities {
  downloadFiles: boolean;
  webWorkers: boolean;
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
