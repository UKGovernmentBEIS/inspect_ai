import Dexie from "dexie";
import { LogDetails, LogPreview } from "../api/types";

// Logs Table - Basic file listing
export interface LogHandleRecord {
  // Auto-incrementing primary key for insertion order
  id?: number;
  file_path: string;
  file_name: string;
  task?: string;
  task_id?: string;
  mtime?: number;
  cached_at: string;
}

// Log Previews Table - Stores results from get_log_summaries()
export interface LogPreviewRecord {
  // Primary key
  file_path: string;

  // The complete log summary object
  preview: LogPreview;

  cached_at: string;
}

// Log Details Table - Stores complete results from get_log_info()
// This includes the full header and sample summaries
export interface LogDetailsRecord {
  // Primary key
  file_path: string;

  // The complete log info object (includes sample summaries)
  details: LogDetails;

  cached_at: string;
}

// Current database schema version
export const DB_VERSION = 9;

// Resolves a log dir into a database name
function resolveDBName(logDir: string): string {
  const sanitizedDir = logDir.replace(/[^a-zA-Z0-9_-]/g, "_");
  const dbName = `InspectAI_${sanitizedDir}`;
  return dbName;
}

export class AppDatabase extends Dexie {
  logs!: Dexie.Table<LogHandleRecord, number>;
  log_previews!: Dexie.Table<LogPreviewRecord, string>;
  log_details!: Dexie.Table<LogDetailsRecord, string>;

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
      logs: "++id, &file_path, mtime, task, task_id, cached_at",

      // Log summaries from get_log_summaries() - indexes for common queries
      log_previews:
        "file_path, preview.status, preview.task_id, preview.model, cached_at",

      // Complete log info from get_log_details() - includes samples
      log_details: "file_path, details.status, cached_at",
    });
  }
}
