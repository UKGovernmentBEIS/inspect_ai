import { StateSnapshot } from "react-virtuoso";
import {
  AttachmentData,
  EvalLogHeader,
  EvalSummary,
  EventData,
  LogFiles,
  PendingSamples,
  SampleSummary,
} from "./api/types";
import { ScorerInfo } from "./scoring/utils";
import {
  ApprovalEvent,
  ContentImage,
  ContentText,
  EvalSample,
  InfoEvent,
  LoggerEvent,
  ModelEvent,
  SampleInitEvent,
  SampleLimitEvent,
  SandboxEvent,
  ScoreEvent,
  StateEvent,
  StepEvent,
  StoreEvent,
  SubtaskEvent,
  ToolEvent,
} from "./types/log";

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
  collapsed: Record<string, boolean>;
  messages: Record<string, boolean>;
  propertyBags: Record<string, Record<string, unknown>>;
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

export type SampleStatus = "ok" | "loading" | "streaming" | "error";

export interface SampleState {
  selectedSample: EvalSample | undefined;
  sampleStatus: SampleStatus;
  sampleError: Error | undefined;

  // Events and attachments
  runningEvents: Event[];
}

export type Event =
  | SampleInitEvent
  | SampleLimitEvent
  | SandboxEvent
  | StateEvent
  | StoreEvent
  | ModelEvent
  | ToolEvent
  | ApprovalEvent
  | InputEvent
  | ScoreEvent
  | ErrorEvent
  | LoggerEvent
  | InfoEvent
  | StepEvent
  | SubtaskEvent;

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
  events: Map<string, EventData>;
  attachments: Map<string, AttachmentData>;
  summary?: SampleSummary;
}
