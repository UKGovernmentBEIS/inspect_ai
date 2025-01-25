import {
  Version,
  Status,
  EvalSpec,
  EvalPlan,
  EvalResults,
  EvalStats,
  EvalError,
  Input,
  Target,
  Scores1,
  Type11,
  EvalLog,
  EvalSample,
} from "../types/log";

export interface EvalSummary {
  version?: Version;
  status?: Status;
  eval: EvalSpec;
  plan?: EvalPlan;
  results?: EvalResults | null;
  stats?: EvalStats;
  error?: EvalError | null;
  sampleSummaries: SampleSummary[];
}

export interface EvalLogHeader {
  version?: Version;
  status?: Status;
  eval: EvalSpec;
  plan?: EvalPlan;
  results?: EvalResults;
  stats?: EvalStats;
  error?: EvalError;
}

export interface SampleSummary {
  id: number | string;
  epoch: number;
  input: Input;
  target: Target;
  scores: Scores1;
  error?: string;
  limit?: Type11;
}

export interface BasicSampleData {
  id: number | string;
  epoch: number;
  target: Target;
  scores: Scores1;
}

export interface Capabilities {
  downloadFiles: boolean;
  webWorkers: boolean;
}

export interface LogViewAPI {
  client_events: () => Promise<any[]>;
  eval_logs: () => Promise<LogFiles | undefined>;
  eval_log: (
    log_file: string,
    headerOnly?: number,
    capabilities?: Capabilities,
  ) => Promise<LogContents>;
  eval_log_size: (log_file: string) => Promise<number>;
  eval_log_bytes: (
    log_file: string,
    start: number,
    end: number,
  ) => Promise<Uint8Array>;
  eval_log_headers: (log_files: string[]) => Promise<EvalLog[]>;
  download_file: (
    filename: string,
    filecontents: string | Blob | ArrayBuffer | ArrayBufferView,
  ) => Promise<void>;
  open_log_file: (logFile: string, log_dir: string) => Promise<void>;
}

export interface ClientAPI {
  client_events: () => Promise<string[]>;
  get_log_paths: () => Promise<LogFiles>;
  get_log_headers: (log_files: string[]) => Promise<EvalLog[]>;
  get_log_summary: (log_file: string) => Promise<EvalSummary>;
  get_log_sample: (
    log_file: string,
    id: string | number,
    epoch: number,
  ) => Promise<EvalSample | undefined>;
  download_file: (
    file_name: string,
    file_contents: string | Blob | ArrayBuffer | ArrayBufferView,
  ) => Promise<void>;
  open_log_file: (log_file: string, log_dir: string) => Promise<void>;
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

export interface LogFiles {
  files: LogFile[];
  log_dir?: string;
}

export interface LogFile {
  name: string;
  task: string;
  task_id: string;
}

export interface LogContents {
  raw: string;
  parsed: EvalLog;
}

export interface LogFilesFetchResponse {
  raw: string;
  parsed: Record<string, EvalHeader>;
}
