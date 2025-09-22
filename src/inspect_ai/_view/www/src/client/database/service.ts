import { databaseManager } from './manager';
import { LogFiles, LogOverview, EvalLogHeader, SampleSummary } from '../api/types';
import { createLogger } from '../../utils/logger';

const log = createLogger('DatabaseService');

export class DatabaseService {
  private switchingInProgress = false;

  private async getDb() {
    const db = databaseManager.getCurrentDatabase();
    if (!db) {
      throw new Error('No database initialized. Call switchToLogDir first.');
    }
    return db;
  }

  async switchLogDir(logDir: string): Promise<void> {
    if (this.switchingInProgress) {
      log.warn(`Already switching to log directory, ignoring request for: ${logDir}`);
      return;
    }

    this.switchingInProgress = true;
    try {
      log.debug(`Switching to log directory: ${logDir}`);
      await databaseManager.switchToLogDir(logDir);
    } finally {
      this.switchingInProgress = false;
    }
  }

  // === LOG FILES ===
  async cacheLogFiles(logFiles: LogFiles): Promise<void> {
    const db = await this.getDb();
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
      const db = await this.getDb();
      const files = await db.log_files.orderBy('cached_at').toArray();

      if (files.length === 0) {
        log.debug('No cached log files found');
        return null;
      }

      log.debug(`Retrieved ${files.length} cached log files`);
      const logDir = databaseManager.getCurrentLogDir() || '';
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
    const db = await this.getDb();
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
      const db = await this.getDb();
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
  async cacheLogHeader(filePath: string, header: EvalLogHeader): Promise<void> {
    const db = await this.getDb();
    const now = new Date().toISOString();

    log.debug(`Caching log header for: ${filePath}`);
    await db.log_headers.put({
      file_path: filePath,
      version: header.version,
      status: header.status,
      eval_spec: header.eval,
      plan: header.plan,
      results: header.results,
      stats: header.stats,
      error: header.error,
      cached_at: now
    });
  }

  async getCachedLogHeader(filePath: string): Promise<EvalLogHeader | null> {
    const db = await this.getDb();
    const record = await db.log_headers.where('file_path').equals(filePath).first();

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
  }

  // === SAMPLE SUMMARIES ===
  async cacheSampleSummaries(filePath: string, summaries: SampleSummary[]): Promise<void> {
    const db = await this.getDb();
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
    const db = await this.getDb();
    const records = await db.sample_summaries.toArray();

    log.debug(`Retrieved ${records.length} sample summaries across all files`);
    return records.map(record => record.summary_data);
  }

  async getSampleSummariesForFile(filePath: string): Promise<SampleSummary[]> {
    const db = await this.getDb();
    const records = await db.sample_summaries
      .where('file_path')
      .equals(filePath)
      .toArray();

    log.debug(`Retrieved ${records.length} sample summaries for: ${filePath}`);
    return records.map(record => record.summary_data);
  }

  // === QUERY OPERATIONS FOR CROSS-FILE SAMPLE VIEWS ===

  /**
   * Get all sample summaries that match specific criteria
   */
  async querySampleSummaries(filter?: {
    completed?: boolean;
    hasError?: boolean;
    scoreRange?: { min: number; max: number; scoreName?: string };
  }): Promise<SampleSummary[]> {
    const db = await this.getDb();
    let collection = db.sample_summaries.toCollection();

    if (filter?.completed !== undefined) {
      collection = collection.filter(record => record.completed === filter.completed);
    }

    if (filter?.hasError === true) {
      collection = collection.filter(record => !!record.error);
    } else if (filter?.hasError === false) {
      collection = collection.filter(record => !record.error);
    }

    if (filter?.scoreRange) {
      const { min, max, scoreName } = filter.scoreRange;
      collection = collection.filter(record => {
        if (!record.scores) return false;

        if (scoreName) {
          const score = record.scores[scoreName];
          const value = typeof score === 'object' ? score?.value : score;
          return typeof value === 'number' && value >= min && value <= max;
        } else {
          // Check any score value
          return Object.values(record.scores).some(score => {
            const value = typeof score === 'object' ? score?.value : score;
            return typeof value === 'number' && value >= min && value <= max;
          });
        }
      });
    }

    const records = await collection.toArray();
    log.debug(`Query returned ${records.length} sample summaries`);
    return records.map(record => record.summary_data);
  }

  // === CACHE MANAGEMENT ===

  /**
   * Clear all cached data (useful for testing or cache reset)
   */
  async clearAllCaches(): Promise<void> {
    const db = await this.getDb();

    log.debug('Clearing all caches');
    await Promise.all([
      db.log_files.clear(),
      db.log_summaries.clear(),
      db.log_headers.clear(),
      db.sample_summaries.clear()
    ]);
  }

  /**
   * Get cache statistics
   */
  async getCacheStats(): Promise<{
    logFiles: number;
    logSummaries: number;
    logHeaders: number;
    sampleSummaries: number;
    logDir: string | null;
  }> {
    const db = await this.getDb();

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
      logDir: databaseManager.getCurrentLogDir()
    };
  }
}

export const databaseService = new DatabaseService();