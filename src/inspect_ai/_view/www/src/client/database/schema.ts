import Dexie from "dexie";
import { LogInfo, LogSummary } from "../api/types";

// Log Files Table - Basic file listing from get_log_root()
export interface LogFileRecord {
  // (primary key)
  file_path: string;
  file_name: string;
  task?: string;
  task_id?: string;

  // TODO: Remove cached_at
  cached_at: string;
}

// Log Summaries Table - Stores results from get_log_summaries()
export interface LogSummaryRecord {
  // Primary key
  file_path: string;
  cached_at: string;

  // The complete log summary object
  summary: LogSummary;
}

// Log Info Table - Stores complete results from get_log_info()
// This includes the full header and sample summaries
export interface LogInfoRecord {
  // Primary key
  file_path: string;
  cached_at: string;

  // The complete log info object (includes sample summaries)
  info: LogInfo;
}

// Current database schema version
export const DB_VERSION = 3;

// Resolves a log dir into a database name
function resolveDBName(logDir: string): string {
  const sanitizedDir = logDir.replace(/[^a-zA-Z0-9_-]/g, "_");
  const dbName = `InspectAI_${sanitizedDir}`;
  return dbName;
}

export class AppDatabase extends Dexie {
  log_files!: Dexie.Table<LogFileRecord, string>;
  log_summaries!: Dexie.Table<LogSummaryRecord, string>;
  log_info!: Dexie.Table<LogInfoRecord, string>;

  /**
   * Check if an existing database needs to be recreated due to version mismatch.
   * Returns true if the database should be deleted and recreated.
   */
  static async checkVersionMismatch(logDir: string): Promise<boolean> {
    const dbName = resolveDBName(logDir);

    try {
      // Check if database exists and get its version
      const existingDb = await Dexie.exists(dbName);
      if (!existingDb) {
        return false;
      }

      // Open with minimal schema to check actual version
      const tempDb = new Dexie(dbName);
      await tempDb.open();
      const currentVersion = tempDb.verno; // Dexie's internal version number
      tempDb.close();

      if (currentVersion !== DB_VERSION) {
        console.log(
          `Database version mismatch (found v${currentVersion}, expected v${DB_VERSION})`,
        );
        return true;
      }
      return false;
    } catch (error) {
      // Database doesn't exist or has issues - let normal flow handle it
      return false;
    }
  }

  constructor(logDir: string) {
    super(resolveDBName(logDir));

    this.version(DB_VERSION).stores({
      // Basic file listing - indexes for querying and sorting
      log_files: "file_path, task, task_id, cached_at",

      // Log summaries from get_log_summaries() - indexes for common queries
      log_summaries:
        "file_path, summary.status, summary.task_id, summary.model, cached_at",

      // Complete log info from get_log_info() - includes samples
      log_info: "file_path, info.status, cached_at",
    });
  }
}
