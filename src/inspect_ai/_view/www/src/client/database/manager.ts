import { AppDatabase } from './schema';
import { createLogger } from '../../utils/logger';

const log = createLogger('DatabaseManager');

class DatabaseManager {
  private currentDatabase: AppDatabase | null = null;
  private currentLogDir: string | null = null;

  async switchToLogDir(logDir: string): Promise<AppDatabase> {
    if (this.currentLogDir === logDir && this.currentDatabase) {
      return this.currentDatabase;
    }

    log.debug(`Switching to log directory: ${logDir}`);

    // Close current database
    if (this.currentDatabase) {
      log.debug(`Closing current database for: ${this.currentLogDir}`);
      this.currentDatabase.close();
    }

    // Create new database for this log directory
    this.currentDatabase = new AppDatabase(logDir);
    this.currentLogDir = logDir;

    try {
      await this.currentDatabase.open();
      log.debug(`Successfully opened database for: ${logDir}`);
    } catch (error) {
      log.error(`Failed to open database for ${logDir}:`, error);
      this.currentDatabase = null;
      this.currentLogDir = null;
      throw error;
    }

    return this.currentDatabase;
  }

  getCurrentDatabase(): AppDatabase | null {
    return this.currentDatabase;
  }

  getCurrentLogDir(): string | null {
    return this.currentLogDir;
  }

  async close(): Promise<void> {
    if (this.currentDatabase) {
      log.debug(`Closing database for: ${this.currentLogDir}`);
      this.currentDatabase.close();
      this.currentDatabase = null;
      this.currentLogDir = null;
    }
  }

  /**
   * Check if a database is currently active
   */
  isActive(): boolean {
    return this.currentDatabase !== null && this.currentLogDir !== null;
  }

  /**
   * Get database info for debugging
   */
  getInfo(): { logDir: string | null; isActive: boolean } {
    return {
      logDir: this.currentLogDir,
      isActive: this.isActive()
    };
  }
}

export const databaseManager = new DatabaseManager();