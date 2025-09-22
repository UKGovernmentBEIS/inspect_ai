import { DatabaseManager } from './manager';
import { AppDatabase } from './schema';
import { LogFiles, LogOverview, EvalLogHeader, SampleSummary } from '../api/types';
import { createLogger } from '../../utils/logger';

const log = createLogger('DatabaseService');

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
      throw new Error('No database initialized. Call openDatabase first.');
    }
    return db;
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
  async cacheLogFiles(logFiles: LogFiles): Promise<void> {
    const db = this.getDb();
    const now = new Date().toISOString();

    const records = logFiles.files.map(file => ({
      file_path: file.name,
      file_name: file.name.split('/').pop() || file.name,
      task: file.task,
      task_id: file.task_id,
      cached_at: now
    }));

    log.debug(`Caching ${records.length} log files`);
    await db.log_files.bulkPut(records);
  }

  async getCachedLogFiles(): Promise<LogFiles | null> {
    try {
      const db = this.getDb();
      const files = await db.log_files.orderBy('cached_at').toArray();

      if (files.length === 0) {
        log.debug('No cached log files found');
        const logDir = this.manager.getLogDir() || '';
        return {
          log_dir: logDir,
          files: []
        };
      }

      log.debug(`Retrieved ${files.length} cached log files`);
      const logDir = this.manager.getLogDir() || '';
      return {
        log_dir: logDir,
        files: files.map(file => ({
          name: file.file_path,
          task: file.task,
          task_id: file.task_id
        }))
      };
    } catch (error) {
      log.error('Error retrieving cached log files:', error);
      return null;
    }
  }

  // === LOG SUMMARIES ===
  async cacheLogSummaries(summaries: Record<string, LogOverview>): Promise<void> {
    const db = this.getDb();
    const now = new Date().toISOString();

    const records = Object.entries(summaries).map(([filePath, overview]) => ({
      file_path: filePath,
      eval_id: overview.eval_id,
      run_id: overview.run_id,
      task: overview.task,
      task_id: overview.task_id,
      task_version: overview.task_version,
      version: overview.version,
      status: overview.status,
      model: overview.model,
      started_at: overview.started_at,
      completed_at: overview.completed_at,
      primary_metric: overview.primary_metric,
      error: overview.error || undefined,
      cached_at: now
    }));

    log.debug(`Caching ${records.length} log summaries`);
    await db.log_summaries.bulkPut(records);
  }

  async getCachedLogSummaries(filePaths: string[]): Promise<Record<string, LogOverview>> {
    try {
      const db = this.getDb();
      const records = await db.log_summaries.where('file_path').anyOf(filePaths).toArray();

      log.debug(`Retrieved ${records.length} cached log summaries out of ${filePaths.length} requested`);

      const result: Record<string, LogOverview> = {};
      for (const record of records) {
        result[record.file_path] = {
          eval_id: record.eval_id,
          run_id: record.run_id,
          task: record.task,
          task_id: record.task_id,
          task_version: record.task_version,
          version: record.version,
          status: record.status,
          model: record.model,
          started_at: record.started_at,
          completed_at: record.completed_at,
          primary_metric: record.primary_metric,
          error: record.error
        };
      }

      return result;
    } catch (error) {
      log.error('Error retrieving cached log summaries:', error);
      return {};
    }
  }

  // === LOG HEADERS ===
  async cacheLogHeaders(filePath: string, header: EvalLogHeader): Promise<void> {
    const db = this.getDb();
    const now = new Date().toISOString();

    const record = {
      file_path: filePath,
      version: header.version,
      status: header.status,
      eval_spec: header.eval,
      plan: header.plan,
      results: header.results,
      stats: header.stats,
      error: header.error,
      cached_at: now
    };

    log.debug(`Caching log header for: ${filePath}`);
    await db.log_headers.put(record);
  }

  async getCachedLogHeader(filePath: string): Promise<EvalLogHeader | null> {
    try {
      const db = this.getDb();
      const record = await db.log_headers.get(filePath);

      if (!record) {
        log.debug(`No cached log header found for: ${filePath}`);
        return null;
      }

      log.debug(`Retrieved cached log header for: ${filePath}`);
      return {
        version: record.version,
        status: record.status,
        eval: record.eval_spec,
        plan: record.plan,
        results: record.results,
        stats: record.stats,
        error: record.error
      };
    } catch (error) {
      log.error(`Error retrieving cached log header for ${filePath}:`, error);
      return null;
    }
  }

  // === SAMPLE SUMMARIES ===
  async cacheSampleSummaries(filePath: string, summaries: SampleSummary[]): Promise<void> {
    const db = this.getDb();
    const now = new Date().toISOString();

    const records = summaries.map(summary => ({
      file_path: filePath,
      uuid: summary.uuid,
      sample_id: summary.id,
      epoch: summary.epoch,
      input: summary.input,
      target: summary.target,
      scores: summary.scores || {},
      error: summary.error,
      limit: summary.limit,
      metadata: summary.metadata,
      completed: summary.completed,
      retries: summary.retries,
      summary_data: summary,
      cached_at: now
    }));

    log.debug(`Caching ${records.length} sample summaries for: ${filePath}`);
    await db.sample_summaries.bulkPut(records);
  }

  async getAllSampleSummaries(): Promise<SampleSummary[]> {
    const db = this.getDb();
    const records = await db.sample_summaries.toArray();

    log.debug(`Retrieved ${records.length} sample summaries across all files`);
    return records.map(record => record.summary_data);
  }

  async getSampleSummariesForFile(filePath: string): Promise<SampleSummary[]> {
    const db = this.getDb();
    const records = await db.sample_summaries.where('file_path').equals(filePath).toArray();

    log.debug(`Retrieved ${records.length} sample summaries for: ${filePath}`);
    return records.map(record => record.summary_data);
  }

  async querySampleSummaries(filter?: {
    completed?: boolean;
    hasError?: boolean;
    scoreRange?: { min: number; max: number; scoreName?: string };
  }): Promise<SampleSummary[]> {
    const db = this.getDb();
    let query = db.sample_summaries.toCollection();

    // Apply filters
    if (filter?.completed !== undefined) {
      query = query.filter(record => record.completed === filter.completed);
    }

    if (filter?.hasError !== undefined) {
      query = query.filter(record => {
        const hasError = !!record.error;
        return hasError === filter.hasError;
      });
    }

    const records = await query.toArray();

    // Apply score range filter (if specified)
    let filtered = records;
    if (filter?.scoreRange) {
      const { min, max, scoreName } = filter.scoreRange;
      filtered = records.filter(record => {
        if (!record.scores) return false;

        // Check specific score or any score
        if (scoreName) {
          const score = record.scores[scoreName];
          return score && score.value >= min && score.value <= max;
        } else {
          // Check if any score is in range
          return Object.values(record.scores).some(
            score => score && score.value >= min && score.value <= max
          );
        }
      });
    }

    log.debug(`Query returned ${filtered.length} sample summaries (filtered from ${records.length})`);
    return filtered.map(record => record.summary_data);
  }

  // === MANAGEMENT ===

  /**
   * Clear all cached data from all tables.
   */
  async clearAllCaches(): Promise<void> {
    const db = this.getDb();

    log.debug('Clearing all caches');
    await Promise.all([
      db.log_files.clear(),
      db.log_summaries.clear(),
      db.log_headers.clear(),
      db.sample_summaries.clear()
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

    const [logFiles, logSummaries, logHeaders, sampleSummaries] = await Promise.all([
      db.log_files.count(),
      db.log_summaries.count(),
      db.log_headers.count(),
      db.sample_summaries.count()
    ]);

    return {
      logFiles,
      logSummaries,
      logHeaders,
      sampleSummaries,
      logDir: this.manager.getLogDir()
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