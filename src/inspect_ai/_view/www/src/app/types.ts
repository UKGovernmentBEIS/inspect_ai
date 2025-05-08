import { StateSnapshot } from "react-virtuoso";
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
} from "../@types/log";
import {
  AttachmentData,
  EvalLogHeader,
  EvalSummary,
  EventData,
  LogFiles,
  PendingSamples,
  SampleSummary,
} from "../client/api/types";
import { ScorerInfo } from "../state/scoring";

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
  urlHash?: string;
  initialState?: {
    log: string;
    sample_id?: string;
    sample_epoch?: string;
  };
  rehydrated?: boolean;
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

  filter: string;
  filterError?: FilterError;

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

export interface SampleFilter {
  value?: string;
  error?: FilterError;
}

export interface FilterError {
  from: number;
  to: number;
  message: string;
  severity: "warning" | "error";
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
