import Dexie from "dexie";
import { EvalHeader, SampleSummary } from "../api/types";

// Log Files Table - Basic file listing from get_log_paths()
export interface LogFileRecord {
  // (primary key)
  file_path: string;
  file_name: string;
  task?: string;
  task_id?: string;

  // TODO: Remove cached_at
  cached_at: string;
}

// Log Headers Table - Stores complete header data
export interface LogHeaderRecord {
  // Primary key
  file_path: string;
  cached_at: string;

  // The complete header object
  header: EvalHeader;
}

// Sample Summaries Table - Stores complete sample data with indexed fields
export interface SampleSummaryRecord {
  // Metadata
  file_path: string;
  cached_at: string;

  // The complete sample summary object
  summary: SampleSummary;
}

export class AppDatabase extends Dexie {
  log_files!: Dexie.Table<LogFileRecord, string>;
  log_headers!: Dexie.Table<LogHeaderRecord, string>;
  sample_summaries!: Dexie.Table<
    SampleSummaryRecord,
    [string, number | string, number]
  >;

  constructor(logDir: string) {
    // Sanitize logDir for database name
    const sanitizedDir = logDir.replace(/[^a-zA-Z0-9_-]/g, "_");
    const dbName = `InspectAI_${sanitizedDir}`;
    super(dbName);

    this.version(1).stores({
      // Basic file listing - indexes for querying and sorting
      log_files: "file_path, task, task_id, cached_at",

      // Full header data - indexes into nested header properties
      log_headers: "file_path, header.version, header.status, cached_at",

      // Sample data - indexes into nested summary properties
      sample_summaries:
        "[file_path+summary.id+summary.epoch], file_path, summary.id, summary.epoch, summary.completed, summary.target, [file_path+summary.completed], summary.uuid",
    });
  }
}
