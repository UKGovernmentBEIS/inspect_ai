import Dexie from 'dexie';
import { SampleSummary } from '../api/types';
import { EvalSpec, EvalPlan, EvalResults, EvalStats, EvalError, EvalMetric } from '../../@types/log';

// Log Files Table - Basic file listing from get_log_paths()
export interface LogFileRecord {
  id?: number;                    // Auto-increment primary key
  file_path: string;              // LogFile.name (unique)
  file_name: string;              // Basename extracted from path
  task?: string;                  // LogFile.task
  task_id?: string;               // LogFile.task_id
  cached_at: string;              // When cached
}

// Log Summaries Table - Summary data from get_log_overviews()
export interface LogSummaryRecord {
  id?: number;                    // Auto-increment primary key
  file_path: string;              // Reference to log file (unique)

  eval_id: string;                // LogOverview.eval_id
  run_id: string;                 // LogOverview.run_id
  task: string;                   // LogOverview.task
  task_id: string;                // LogOverview.task_id
  task_version: number | string;  // LogOverview.task_version
  version?: number;               // LogOverview.version
  status?: 'started' | 'success' | 'cancelled' | 'error'; // LogOverview.status
  model: string;                  // LogOverview.model
  started_at?: string;            // LogOverview.started_at
  completed_at?: string;          // LogOverview.completed_at
  primary_metric?: EvalMetric;    // LogOverview.primary_metric (full object)
  error?: EvalError;              // LogOverview.error (full object)

  cached_at: string;              // When cached
}

// Log Headers Table - Full header data from get_log_summary()
export interface LogHeaderRecord {
  id?: number;                    // Auto-increment primary key
  file_path: string;              // Reference to log file (unique)

  version?: number;               // EvalLogHeader.version
  status?: 'started' | 'success' | 'cancelled' | 'error'; // EvalLogHeader.status
  eval_spec: EvalSpec;            // EvalLogHeader.eval (full object)
  plan?: EvalPlan;                // EvalLogHeader.plan (full object)
  results?: EvalResults;          // EvalLogHeader.results (full object)
  stats?: EvalStats;              // EvalLogHeader.stats (full object)
  error?: EvalError;              // EvalLogHeader.error (full object)

  cached_at: string;              // When cached
}

// Sample Summaries Table - Sample data for cross-file querying
export interface SampleSummaryRecord {
  id?: number;                    // Auto-increment primary key
  file_path: string;              // Reference to log file

  // Core identifiers from SampleSummary
  uuid?: string;                  // SampleSummary.uuid
  sample_id: number | string;     // SampleSummary.id
  epoch: number;                  // SampleSummary.epoch

  // Content for querying
  input: any;                     // SampleSummary.input (string or ChatMessage[])
  target: string | string[];      // SampleSummary.target
  scores: Record<string, any>;    // SampleSummary.scores (Record<string, Score>)
  error?: string;                 // SampleSummary.error
  limit?: string;                 // SampleSummary.limit
  metadata?: Record<string, any>; // SampleSummary.metadata
  completed?: boolean;            // SampleSummary.completed
  retries?: number;               // SampleSummary.retries

  // Full summary for complete access
  summary_data: SampleSummary;    // Complete original object
  cached_at: string;              // When cached
}

export class AppDatabase extends Dexie {
  log_files!: Dexie.Table<LogFileRecord, number>;
  log_summaries!: Dexie.Table<LogSummaryRecord, number>;
  log_headers!: Dexie.Table<LogHeaderRecord, number>;
  sample_summaries!: Dexie.Table<SampleSummaryRecord, number>;

  constructor(logDir: string) {
    // Sanitize logDir for database name
    const sanitizedDir = logDir.replace(/[^a-zA-Z0-9_-]/g, '_');
    const dbName = `InspectAI_${sanitizedDir}`;
    super(dbName);

    this.version(1).stores({
      log_files: '++id, file_path, task, task_id, cached_at',

      log_summaries: '++id, file_path, eval_id, run_id, task, task_id, status, model, started_at, completed_at',

      log_headers: '++id, file_path, status, cached_at',

      sample_summaries: `
        ++id,
        file_path,
        sample_id,
        epoch,
        completed,
        target,
        [file_path+sample_id+epoch],
        [file_path+completed]
      `
    });
  }
}