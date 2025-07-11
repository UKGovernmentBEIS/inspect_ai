import {
  ColumnFiltersState,
  ColumnResizeMode,
  SortingState,
} from "@tanstack/react-table";
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
  LogFile,
  LogFiles,
  LogOverview,
  PendingSamples,
  SampleSummary,
} from "../client/api/types";
import { ScorerInfo } from "../state/scoring";

export interface AppState {
  status: AppStatus;
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
  pagination: Record<string, { page: number; pageSize: number }>;
  singleFileMode?: boolean;
}

export interface LogsState {
  logs: LogFiles;
  logOverviews: Record<string, LogOverview>;
  logOverviewsLoading: boolean;
  selectedLogIndex: number;
  selectedLogFile?: string;
  listing: LogsListing;
  loadingFiles: Set<string>;
  pendingRequests: Map<string, Promise<EvalLogHeader | null>>;
}

export interface LogsListing {
  sorting?: SortingState;
  filtering?: ColumnFiltersState;
  globalFilter?: string;
  columnResizeMode?: ColumnResizeMode;
  columnSizes?: Record<string, number>;
  filteredCount?: number;
  watchedLogs?: LogFile[];
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

export type SampleIdentifier = {
  id: string | number;
  epoch: number;
};

export interface SampleState {
  sample_identifier: SampleIdentifier | undefined;
  sampleInState: boolean;
  selectedSampleObject?: EvalSample;
  sampleStatus: SampleStatus;
  sampleError: Error | undefined;
  sampleNeedsReload: number;

  visiblePopover?: string;

  // Events and attachments
  runningEvents: Event[];
  collapsedEvents: Record<string, Record<string, boolean>> | null;
  collapsedIdBuckets: Record<string, Record<string, boolean>>;

  selectedOutlineId?: string;
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
