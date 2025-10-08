import { createLogger } from "../../utils/logger";
import { LogHandle, LogInfo, LogPreview, SampleSummary } from "../api/types";
import { DatabaseManager } from "./manager";
import { AppDatabase } from "./schema";

const log = createLogger("DatabaseService");

/**
 * Database service for caching and retrieving log data.
 * Works with a DatabaseManager instance to handle database operations.
 */
export class DatabaseService {
  private manager: DatabaseManager;

  constructor(manager: DatabaseManager) {
    this.manager = manager;
  }

  /**
   * Get the current database instance.
   * Throws an error if no database is open.
   */
  private getDb(): AppDatabase {
    const db = this.manager.getDatabase();
    if (!db) {
      throw new Error("No database initialized. Call openDatabase first.");
    }
    return db;
  }

  opened(): boolean {
    return this.manager.getDatabase() !== null;
  }

  /**
   * Open a database for the specified log directory.
   */
  async openDatabase(logDir: string): Promise<void> {
    await this.manager.openDatabase(logDir);
  }

  /**
   * Close the current database connection.
   */
  async closeDatabase(): Promise<void> {
    await this.manager.close();
  }

  /**
   * Get the current log directory.
   */
  getLogDir(): string | null {
    return this.manager.getLogDir();
  }

  // === LOG FILES ===
  async writeLogs(logs: LogHandle[]): Promise<void> {
    const db = this.getDb();
    const now = new Date().toISOString();

    // Get existing records to preserve their IDs
    const existingRecords = await db.logs.toArray();
    const existingByPath = new Map(
      existingRecords.map((r) => [r.file_path, r.id]),
    );

    const records = logs.map((file) => ({
      id: existingByPath.get(file.name),
      file_path: file.name,
      file_name: file.name.split("/").pop() || file.name,
      task: file.task,
      task_id: file.task_id,
      mtime: file.mtime,
      cached_at: now,
    }));

    log.debug(`Caching ${records.length} log files`);
    await db.logs.bulkPut(records);
  }

  async readLogs(): Promise<LogHandle[] | null> {
    try {
      if (!this.opened()) {
        log.debug("Database not open");
        return null;
      }

      const db = this.getDb();
      const files = await db.logs.orderBy("id").toArray();

      if (files.length === 0) {
        log.debug("No cached log files found");
        return [];
      }

      log.debug(`Retrieved ${files.length} cached log files`);
      return files.map((file) => ({
        name: file.file_path,
        task: file.task,
        task_id: file.task_id,
        mtime: file.mtime,
      }));
    } catch (error) {
      log.error("Error retrieving cached log files:", error);
      return null;
    }
  }

  // === LOG PREVIEWS ===
  async writeLogPreviews(
    previews: LogPreview[],
    filePaths: string[],
  ): Promise<void> {
    const db = this.getDb();
    const now = new Date().toISOString();

    const records = previews.map((summary, index) => ({
      file_path: filePaths[index],
      cached_at: now,
      preview: summary,
    }));

    log.debug(`Caching ${records.length} log previews`);
    await db.log_previews.bulkPut(records);
  }

  async readLogPreviews(
    logs: LogHandle[],
  ): Promise<Record<string, LogPreview>> {
    try {
      const filePaths = logs.map((log) => log.name);
      const db = this.getDb();
      const records = await db.log_previews
        .where("file_path")
        .anyOf(filePaths)
        .toArray();

      log.debug(
        `Retrieved ${records.length} cached log previews out of ${filePaths.length} requested`,
      );

      const result: Record<string, LogPreview> = {};
      for (const record of records) {
        result[record.file_path] = record.preview;
      }

      return result;
    } catch (error) {
      log.error("Error retrieving cached log summaries:", error);
      return {};
    }
  }

  // === LOG DETAILS ===
  async writeLogDetails(filePath: string, info: LogInfo): Promise<void> {
    const db = this.getDb();
    const now = new Date().toISOString();

    const record = {
      file_path: filePath,
      cached_at: now,
      details: info,
    };

    log.debug(`Caching log info for: ${filePath}`);
    await db.log_details.put(record);
  }

  async readLogDetails(filePath: string): Promise<LogInfo | null> {
    try {
      const db = this.getDb();
      const record = await db.log_details.get(filePath);

      if (!record) {
        log.debug(`No cached log info found for: ${filePath}`);
        return null;
      }

      log.debug(`Retrieved cached log info for: ${filePath}`);
      return record.details;
    } catch (error) {
      log.error(`Error retrieving cached log info for ${filePath}:`, error);
      return null;
    }
  }

  // === SAMPLE SUMMARIES (extracted from LogDetails) ===
  async readAllSampleSummaries(): Promise<SampleSummary[]> {
    const db = this.getDb();
    const records = await db.log_details.toArray();

    const allSummaries: SampleSummary[] = [];
    for (const record of records) {
      if (record.details.sampleSummaries) {
        allSummaries.push(...record.details.sampleSummaries);
      }
    }

    log.debug(
      `Retrieved ${allSummaries.length} sample summaries across all files`,
    );
    return allSummaries;
  }

  async readSampleSummariesForFile(filePath: string): Promise<SampleSummary[]> {
    const logInfo = await this.readLogDetails(filePath);
    if (!logInfo || !logInfo.sampleSummaries) {
      return [];
    }
    return logInfo.sampleSummaries;
  }

  async querySampleSummaries(filter?: {
    completed?: boolean;
    hasError?: boolean;
    scoreRange?: { min: number; max: number; scoreName?: string };
  }): Promise<SampleSummary[]> {
    const allSummaries = await this.readAllSampleSummaries();

    let filtered = allSummaries;

    // Apply filters
    if (filter?.completed !== undefined) {
      filtered = filtered.filter(
        (summary) => summary.completed === filter.completed,
      );
    }

    if (filter?.hasError !== undefined) {
      filtered = filtered.filter((summary) => {
        const hasError = !!summary.error;
        return hasError === filter.hasError;
      });
    }

    // Apply score range filter (if specified)
    if (filter?.scoreRange) {
      const { min, max, scoreName } = filter.scoreRange;
      filtered = filtered.filter((summary) => {
        if (!summary.scores) return false;

        // Check specific score or any score
        if (scoreName) {
          const score = summary.scores[scoreName];
          return (
            score &&
            typeof score.value === "number" &&
            score.value >= min &&
            score.value <= max
          );
        } else {
          // Check if any score is in range
          return Object.values(summary.scores).some(
            (score) =>
              score &&
              typeof score.value === "number" &&
              score.value >= min &&
              score.value <= max,
          );
        }
      });
    }

    log.debug(
      `Query returned ${filtered.length} sample summaries (filtered from ${allSummaries.length})`,
    );
    return filtered;
  }

  // === MANAGEMENT ===

  /**
   * Clear all cached data from all tables.
   */
  async clearAllCaches(): Promise<void> {
    const db = this.getDb();

    log.debug("Clearing all caches");
    await Promise.all([
      db.logs.clear(),
      db.log_previews.clear(),
      db.log_details.clear(),
    ]);
  }

  /**
   * Clear cache for a specific log file
   */
  async clearCacheForFile(filePath: string): Promise<void> {
    const db = this.getDb();
    log.debug(`Clearing cache for file: ${filePath}`);

    await Promise.all([
      db.logs.where("file_path").equals(filePath).delete(),
      db.log_previews.where("file_path").equals(filePath).delete(),
      db.log_details.where("file_path").equals(filePath).delete(),
    ]);
  }

  /**
   * Get cache statistics.
   */
  async getCacheStats(): Promise<{
    logFiles: number;
    logSummaries: number;
    logHeaders: number;
    sampleSummaries: number;
    logDir: string | null;
  }> {
    const db = this.getDb();

    const [logFiles, logSummaries, logInfo] = await Promise.all([
      db.logs.count(),
      db.log_previews.count(),
      db.log_details.count(),
    ]);

    // Count sample summaries from log info
    let sampleSummaries = 0;
    const logInfoRecords = await db.log_details.toArray();
    for (const record of logInfoRecords) {
      if (record.details.sampleSummaries) {
        sampleSummaries += record.details.sampleSummaries.length;
      }
    }

    return {
      logFiles,
      logSummaries,
      logHeaders: logInfo, // For backward compatibility
      sampleSummaries,
      logDir: this.manager.getLogDir(),
    };
  }
}

/**
 * Create a new database service instance.
 * Each service instance works with its own database manager.
 */
export function createDatabaseService(): DatabaseService {
  const manager = new DatabaseManager();
  return new DatabaseService(manager);
}
