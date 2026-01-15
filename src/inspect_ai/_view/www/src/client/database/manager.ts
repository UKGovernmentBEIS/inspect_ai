import Dexie from "dexie";
import { createLogger } from "../../utils/logger";
import { AppDatabase } from "./schema";

const log = createLogger("DatabaseManager");

/**
 * Manages database instances for different log directories.
 * Each instance of this class manages a single database connection.
 */
export class DatabaseManager {
  private database: AppDatabase | null = null;
  private databaseHandle: string | null = null;

  /**
   * Opens a database for the specified log directory.
   * If already connected to this directory, returns the existing connection.
   * If connected to a different directory, closes the current connection first.
   */
  async openDatabase(databaseHandle: string): Promise<AppDatabase> {
    if (this.databaseHandle === databaseHandle && this.database) {
      return this.database;
    }

    log.debug(`Opening database for log directory: ${databaseHandle}`);

    // Close current database if switching to a different directory
    if (this.database && this.databaseHandle !== databaseHandle) {
      await this.close();
    }

    // Check for version mismatch before opening
    const needsRecreation =
      await AppDatabase.checkVersionMismatch(databaseHandle);
    if (needsRecreation) {
      log.info(
        `Recreating database due to version mismatch for: ${databaseHandle}`,
      );
      const sanitizedDir = databaseHandle.replace(/[^a-zA-Z0-9_-]/g, "_");
      const dbName = `InspectAI_${sanitizedDir}`;
      await Dexie.delete(dbName);
      log.debug(`Deleted old database: ${dbName}`);
    }

    // Create and open new database
    this.database = new AppDatabase(databaseHandle);
    this.databaseHandle = databaseHandle;

    try {
      await this.database.open();
      log.debug(`Successfully opened database for: ${databaseHandle}`);
      return this.database;
    } catch (error) {
      log.error(`Failed to open database for ${databaseHandle}:`, error);
      this.database = null;
      this.databaseHandle = null;
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
  getDatabaseHandle(): string | null {
    return this.databaseHandle;
  }

  /**
   * Close the current database connection.
   */
  async close(): Promise<void> {
    if (this.database) {
      log.debug(`Closing database for: ${this.databaseHandle}`);
      this.database.close();
      this.database = null;
      this.databaseHandle = null;
    }
  }

  /**
   * Check if a database is currently open.
   */
  isOpen(): boolean {
    return this.database !== null && this.databaseHandle !== null;
  }

  /**
   * Get database info for debugging.
   */
  getInfo(): { databaseHandle: string | null; isOpen: boolean } {
    return {
      databaseHandle: this.databaseHandle,
      isOpen: this.isOpen(),
    };
  }
}
