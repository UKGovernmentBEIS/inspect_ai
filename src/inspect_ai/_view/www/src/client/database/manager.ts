import Dexie from "dexie";
import { AppDatabase } from "./schema";
import { createLogger } from "../../utils/logger";

const log = createLogger("DatabaseManager");

/**
 * Manages database instances for different log directories.
 * Each instance of this class manages a single database connection.
 */
export class DatabaseManager {
  private database: AppDatabase | null = null;
  private logDir: string | null = null;

  /**
   * Opens a database for the specified log directory.
   * If already connected to this directory, returns the existing connection.
   * If connected to a different directory, closes the current connection first.
   */
  async openDatabase(logDir: string): Promise<AppDatabase> {
    if (this.logDir === logDir && this.database) {
      return this.database;
    }

    log.debug(`Opening database for log directory: ${logDir}`);

    // Close current database if switching to a different directory
    if (this.database && this.logDir !== logDir) {
      await this.close();
    }

    // Check for version mismatch before opening
    const needsRecreation = await AppDatabase.checkVersionMismatch(logDir);
    if (needsRecreation) {
      log.info(`Recreating database due to version mismatch for: ${logDir}`);
      const sanitizedDir = logDir.replace(/[^a-zA-Z0-9_-]/g, "_");
      const dbName = `InspectAI_${sanitizedDir}`;
      await Dexie.delete(dbName);
      log.debug(`Deleted old database: ${dbName}`);
    }

    // Create and open new database
    this.database = new AppDatabase(logDir);
    this.logDir = logDir;

    try {
      await this.database.open();
      log.debug(`Successfully opened database for: ${logDir}`);
      return this.database;
    } catch (error) {
      log.error(`Failed to open database for ${logDir}:`, error);
      this.database = null;
      this.logDir = null;
      throw error;
    }
  }

  /**
   * Get the current database instance.
   * Returns null if no database is open.
   */
  getDatabase(): AppDatabase | null {
    return this.database;
  }

  /**
   * Get the current log directory.
   * Returns null if no database is open.
   */
  getLogDir(): string | null {
    return this.logDir;
  }

  /**
   * Close the current database connection.
   */
  async close(): Promise<void> {
    if (this.database) {
      log.debug(`Closing database for: ${this.logDir}`);
      this.database.close();
      this.database = null;
      this.logDir = null;
    }
  }

  /**
   * Check if a database is currently open.
   */
  isOpen(): boolean {
    return this.database !== null && this.logDir !== null;
  }

  /**
   * Get database info for debugging.
   */
  getInfo(): { logDir: string | null; isOpen: boolean } {
    return {
      logDir: this.logDir,
      isOpen: this.isOpen(),
    };
  }
}
