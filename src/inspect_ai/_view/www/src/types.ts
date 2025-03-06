import {
  EvalLogHeader,
  EvalSummary,
  LogFiles,
  PendingSamples,
  SampleSummary,
} from "./api/types";
import { ScorerInfo } from "./scoring/utils";
import { ContentImage, ContentText, EvalSample, Events } from "./types/log";

export interface AppState {
  status: AppStatus;
  offcanvas: boolean;
  showFind: boolean;
  tabs: {
    workspace: string;
    sample: string;
  };
  dialogs: {
    sample: boolean;
  };
  scrollPositions: Record<string, number>;
  listPositions: Record<string, StateSnapshot>;
}

export interface LogsState {
  logs: LogFiles;
  logHeaders: Record<string, EvalLogHeader>;
  headersLoading: boolean;
  selectedLogIndex: number;
}

export interface LogState {
  loadedLog?: string;

  selectedSampleIndex: number;
  selectedLogSummary?: EvalSummary;
  pendingSampleSummaries?: PendingSamples;

  filter: ScoreFilter;
  epoch: string;
  sort: string;
  score?: ScoreLabel;
  scores?: ScorerInfo[];
}

export type SampleStatus = "ok" | "loading" | "error";

export interface SampleState {
  selectedSample: EvalSample | undefined;
  sampleStatus: SampleStatus;
  sampleError: Error | undefined;
  runningSampleData: RunningSampleData | undefined;
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
