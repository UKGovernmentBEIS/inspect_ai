import { GridState } from "ag-grid-community";
import { StateSnapshot } from "react-virtuoso";
import {
  ApprovalEvent,
  CompactionEvent,
  ContentImage,
  ContentText,
  EvalSample,
  EvalSet,
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
  EvalHeader,
  EventData,
  LogDetails,
  LogHandle,
  LogPreview,
  PendingSamples,
  SampleSummary,
} from "../client/api/types";

export interface AppState {
  status: AppStatus;
  nativeFind?: boolean;
  showFind: boolean;
  tabs: {
    workspace: string;
    sample: string;
  };
  dialogs: {
    transcriptFilter: boolean;
    options: boolean;
  };
  scrollPositions: Record<string, number>;
  listPositions: Record<string, StateSnapshot>;
  visibleRanges: Record<string, { startIndex: number; endIndex: number }>;
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
  singleFileMode?: boolean;
  displayMode?: "rendered" | "raw";
  logsSampleView: boolean;
}

export interface DisplayedSample {
  logFile: string;
  sampleId: string | number;
  epoch: number;
}

export interface LogsState {
  logDir?: string;
  logs: LogHandle[];
  logPreviews: Record<string, LogPreview>;
  logDetails: Record<string, LogDetails>;
  evalSet?: EvalSet;
  selectedLogFile?: string;
  listing: LogsListing;
  pendingRequests: Map<string, Promise<EvalHeader | null>>;
  dbStats: {
    logCount: number;
    previewCount: number;
    detailsCount: number;
  };
  samplesListState: {
    gridState?: GridState;
    displayedSamples?: Array<DisplayedSample>;
    columnVisibility: Record<string, boolean>;
    previousSamplesPath?: string;
  };
  flow?: string;
  flowDir?: string;
  showRetriedLogs: boolean;
}

export interface LogsListing {
  filteredCount?: number;
  watchedLogs?: LogHandle[];
  selectedRowIndex?: number | null;
  gridState?: GridState;
  previousLogPath?: string;
  columnVisibility: Record<string, boolean>;
}

export interface SampleHandle {
  id: string | number;
  epoch: number;
  logFile: string;
}

export interface LogState {
  loadedLog?: string;

  selectedSampleHandle?: SampleHandle;
  selectedLogDetails?: LogDetails;
  pendingSampleSummaries?: PendingSamples;

  filter: string;
  filterError?: FilterError;

  selectedScores?: ScoreLabel[];
  scores?: ScoreLabel[];

  filteredSampleCount?: number;
}

export type SampleStatus = "ok" | "loading" | "streaming" | "error";

export interface EventFilter {
  filteredTypes: string[];
}

export interface SampleState {
  sample_identifier: SampleHandle | undefined;
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
  collapsedMode: "collapsed" | "expanded" | null;
  eventFilter: EventFilter;

  selectedOutlineId?: string;
}

export type Event =
  | SampleInitEvent
  | SampleLimitEvent
  | CompactionEvent
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
  // Waiting while loading data, show large form of progress
  loading: number;

  // Background syncing data, show small form of activity
  syncing: boolean;
  error?: Error;
}

export interface CurrentLog {
  name: string;
  contents: LogDetails;
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
