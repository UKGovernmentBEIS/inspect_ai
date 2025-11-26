import {
  ApprovalEvent,
  CompletedAt,
  EvalError,
  EvalId,
  EvalLog,
  EvalMetric,
  EvalPlan,
  EvalResults,
  EvalSample,
  EvalSet,
  EvalSpec,
  EvalStats,
  InfoEvent,
  Input,
  LoggerEvent,
  Model,
  ModelEvent,
  RunId,
  SampleInitEvent,
  SampleLimitEvent,
  SandboxEvent,
  ScoreEvent,
  Scores1,
  StartedAt,
  StateEvent,
  Status,
  StepEvent,
  StoreEvent,
  SubtaskEvent,
  Target,
  Task,
  TaskId,
  TaskVersion,
  ToolEvent,
  Version,
} from "../../@types/log";

export interface LogDetails {
  version?: Version;
  status?: Status;
  eval: EvalSpec;
  plan?: EvalPlan;
  results?: EvalResults | null;
  stats?: EvalStats;
  error?: EvalError | null;
  sampleSummaries: SampleSummary[];
}

export interface LogFilesResponse {
  files: LogHandle[];
  response_type: "incremental" | "full";
}

export interface PendingSampleResponse {
  pendingSamples?: PendingSamples;
  status: "NotModified" | "NotFound" | "OK";
}

export interface SampleDataResponse {
  sampleData?: SampleData;
  status: "NotModified" | "NotFound" | "OK";
}

export interface RunningMetric {
  scorer: string;
  name: string;
  value?: number | null;
  reducer?: string;
  params?: {};
}

export interface PendingSamples {
  metrics?: RunningMetric[];
  samples: SampleSummary[];
  refresh: number;
  etag?: string;
}

export interface SampleData {
  events: EventData[];
  attachments: AttachmentData[];
}

export interface EventData {
  id: number;
  event_id: string;
  sample_id: string;
  epoch: number;
  event:
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
}

export interface AttachmentData {
  id: number;
  sample_id: string;
  epoch: number;
  hash: string;
  content: string;
}

export interface SampleSummary {
  uuid?: string;
  id: number | string;
  epoch: number;
  input: Input;
  target: Target;
  scores: Scores1;
  error?: string;
  limit?: string;
  metadata?: Record<string, any>;
  completed?: boolean;
  retries?: number;
}

export interface BasicSampleData {
  id: number | string;
  epoch: number;
  target: Target;
  scores: Scores1;
}

export interface Capabilities {
  downloadFiles: boolean;
  downloadLogs: boolean;
  webWorkers: boolean;
  streamSamples: boolean;
  streamSampleData: boolean;
}

export interface LogViewAPI {
  client_events: () => Promise<any[]>;
  get_eval_set: (dir?: string) => Promise<EvalSet | undefined>;
  get_flow: (dir?: string) => Promise<string | undefined>;
  get_log_dir?: () => Promise<string | undefined>;
  get_logs?: (
    mtime: number,
    clientFileCount: number,
  ) => Promise<LogFilesResponse>;
  get_log_root: () => Promise<LogRoot | undefined>;
  get_log_contents: (
    log_file: string,
    // This is the number of MB of the log to fetch. If the log is larger than this, only the header will be returned. If not provided, it always fetches the entire log. Really only user for old JSON logs.
    headerOnly?: number,
    capabilities?: Capabilities,
  ) => Promise<LogContents>;
  get_log_size: (log_file: string) => Promise<number>;
  get_log_bytes: (
    log_file: string,
    start: number,
    end: number,
  ) => Promise<Uint8Array>;
  get_log_summary?: (log_file: string) => Promise<LogPreview>;
  get_log_summaries: (log_files: string[]) => Promise<LogPreview[]>;
  log_message: (log_file: string, message: string) => Promise<void>;
  download_file: (
    filename: string,
    filecontents: string | Blob | ArrayBuffer | ArrayBufferView<ArrayBuffer>,
  ) => Promise<void>;
  download_log?: (log_file: string) => Promise<void>;
  open_log_file: (logFile: string, log_dir: string) => Promise<void>;
  eval_pending_samples?: (
    log_file: string,
    etag?: string,
  ) => Promise<PendingSampleResponse>;
  eval_log_sample_data?: (
    log_file: string,
    id: string | number,
    epoch: number,
    last_event?: number,
    last_attachment?: number,
  ) => Promise<SampleDataResponse | undefined>;
}

export interface ClientAPI {
  // Basic initialization
  get_log_dir: () => Promise<string | undefined>;

  // List of files
  get_logs: (
    mtime: number,
    clientFileCount: number,
  ) => Promise<LogFilesResponse>;

  // Log files retrieval
  // Legacy: Read the files and log directory in a single request
  get_log_root: () => Promise<LogRoot>;

  // Read eval set
  get_eval_set: (dir?: string) => Promise<EvalSet | undefined>;

  // Read flow data
  get_flow: (dir?: string) => Promise<string | undefined>;

  get_log_summaries: (log_files: string[]) => Promise<LogPreview[]>;
  get_log_details: (log_file: string) => Promise<LogDetails>;

  // Sample retrieval
  get_log_sample: (
    log_file: string,
    id: string | number,
    epoch: number,
  ) => Promise<EvalSample | undefined>;
  get_log_pending_samples?: (
    log_file: string,
    etag?: string,
  ) => Promise<PendingSampleResponse>;
  get_log_sample_data?: (
    log_file: string,
    id: string | number,
    epoch: number,
    last_event?: number,
    last_attachment?: number,
  ) => Promise<SampleDataResponse | undefined>;

  // Events
  client_events: () => Promise<string[]>;

  // Logging
  log_message?: (log_file: string, message: string) => Promise<void>;

  // File operations (for the client)
  download_file: (
    file_name: string,
    file_contents: string | Blob | ArrayBuffer | ArrayBufferView<ArrayBuffer>,
  ) => Promise<void>;
  download_log?: (log_file: string) => Promise<void>;
  open_log_file: (log_file: string, log_dir: string) => Promise<void>;
}

export interface ClientStorage {
  getItem: (name: string) => unknown;
  setItem: (name: string, value: unknown) => void;
  removeItem: (name: string) => void;
}

export interface FetchResponse {
  raw: string;
  parsed: Record<string, any>;
}

export interface EvalHeader {
  version?: Version;
  status?: Status;
  eval: EvalSpec;
  plan?: EvalPlan;
  results?: EvalResults | null;
  stats?: EvalStats;
  error?: EvalError | null;
}

export interface LogPreview {
  eval_id: EvalId;
  run_id: RunId;

  task: Task;
  task_id: TaskId;
  task_version: TaskVersion;

  version?: Version;
  status?: Status;
  error?: EvalError | null;

  model: Model;

  started_at?: StartedAt;
  completed_at?: CompletedAt;

  primary_metric?: EvalMetric;
}

export interface LogRoot {
  logs: LogHandle[];
  log_dir?: string;
}

export interface LogHandle {
  name: string;
  task?: string;
  task_id?: string;
  mtime?: number;
}

export interface LogContents {
  raw: string;
  parsed: EvalLog;
}

export interface LogFilesFetchResponse {
  raw: string;
  parsed: Record<string, LogPreview>;
}

export interface UpdateStateMessage {
  data: {
    type: "updateState";
    url: string;
    sample_id?: string;
    sample_epoch?: string;
  };
}

export interface BackgroundUpdateMessage {
  data: {
    type: "backgroundUpdate";
    url: string;
    log_dir: string;
  };
}
export type HostMessage = UpdateStateMessage | BackgroundUpdateMessage;
