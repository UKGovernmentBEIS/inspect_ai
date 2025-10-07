import { createLogger } from "../../utils/logger";
import { LogFile, LogInfo, LogSummary, SampleSummary } from "../api/types";
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
  async cacheLogFiles(logFiles: LogFile[]): Promise<void> {
    const db = this.getDb();
    const now = new Date().toISOString();

    // Get existing records to preserve their IDs
    const existingRecords = await db.log_files.toArray();
    const existingByPath = new Map(
      existingRecords.map((r) => [r.file_path, r.id]),
    );

    const records = logFiles.map((file) => ({
      id: existingByPath.get(file.name),
      file_path: file.name,
      file_name: file.name.split("/").pop() || file.name,
      task: file.task,
      task_id: file.task_id,
      mtime: file.mtime,
      cached_at: now,
    }));

    log.debug(`Caching ${records.length} log files`);
    await db.log_files.bulkPut(records);
  }

  async getCachedLogFiles(): Promise<LogFile[] | null> {
    try {
      if (!this.opened()) {
        log.debug("Database not open");
        return null;
      }

      const db = this.getDb();
      const files = await db.log_files.orderBy("id").toArray();

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

  // === LOG SUMMARIES ===
  async cacheLogSummaries(
    summaries: LogSummary[],
    filePaths: string[],
  ): Promise<void> {
    const db = this.getDb();
    const now = new Date().toISOString();

    const records = summaries.map((summary, index) => ({
      file_path: filePaths[index],
      cached_at: now,
      summary: summary,
    }));

    log.debug(`Caching ${records.length} log summaries`);
    await db.log_summaries.bulkPut(records);
  }

  async getCachedLogSummaries(
    filePaths: string[],
  ): Promise<Record<string, LogSummary>> {
    try {
      const db = this.getDb();
      const records = await db.log_summaries
        .where("file_path")
        .anyOf(filePaths)
        .toArray();

      log.debug(
        `Retrieved ${records.length} cached log summaries out of ${filePaths.length} requested`,
      );

      const result: Record<string, LogSummary> = {};
      for (const record of records) {
        result[record.file_path] = record.summary;
      }

      return result;
    } catch (error) {
      log.error("Error retrieving cached log summaries:", error);
      return {};
    }
  }

  // === LOG INFO ===
  async cacheLogInfo(filePath: string, info: LogInfo): Promise<void> {
    const db = this.getDb();
    const now = new Date().toISOString();

    const record = {
      file_path: filePath,
      cached_at: now,
      info: info,
    };

    log.debug(`Caching log info for: ${filePath}`);
    await db.log_info.put(record);
  }

  async getCachedLogInfo(filePath: string): Promise<LogInfo | null> {
    try {
      const db = this.getDb();
      const record = await db.log_info.get(filePath);

      if (!record) {
        log.debug(`No cached log info found for: ${filePath}`);
        return null;
      }

      log.debug(`Retrieved cached log info for: ${filePath}`);
      return record.info;
    } catch (error) {
      log.error(`Error retrieving cached log info for ${filePath}:`, error);
      return null;
    }
  }

  // === SAMPLE SUMMARIES (extracted from LogInfo) ===
  async getAllSampleSummaries(): Promise<SampleSummary[]> {
    const db = this.getDb();
    const records = await db.log_info.toArray();

    const allSummaries: SampleSummary[] = [];
    for (const record of records) {
      if (record.info.sampleSummaries) {
        allSummaries.push(...record.info.sampleSummaries);
      }
    }

    log.debug(
      `Retrieved ${allSummaries.length} sample summaries across all files`,
    );
    return allSummaries;
  }

  async getSampleSummariesForFile(filePath: string): Promise<SampleSummary[]> {
    const logInfo = await this.getCachedLogInfo(filePath);
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
    const allSummaries = await this.getAllSampleSummaries();

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
      db.log_files.clear(),
      db.log_summaries.clear(),
      db.log_info.clear(),
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
      db.log_files.count(),
      db.log_summaries.count(),
      db.log_info.count(),
    ]);

    // Count sample summaries from log info
    let sampleSummaries = 0;
    const logInfoRecords = await db.log_info.toArray();
    for (const record of logInfoRecords) {
      if (record.info.sampleSummaries) {
        sampleSummaries += record.info.sampleSummaries.length;
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
