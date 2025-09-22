/**
 * Manual testing utilities for database functionality
 * These can be called from browser console when needed
 */

import { databaseService } from './service';

// Make database testing available in browser console
declare global {
  interface Window {
    inspectDB: {
      init: (logDir: string) => Promise<void>;
      test: () => Promise<boolean>;
      stats: () => Promise<void>;
      clear: () => Promise<void>;
    };
  }
}

async function initDatabase(logDir: string) {
  console.log(`🗄️ Initializing database for: ${logDir}`);
  try {
    await databaseService.switchLogDir(logDir);
    console.log('✅ Database initialized successfully');
  } catch (error) {
    console.error('❌ Database initialization failed:', error);
  }
}

async function testDatabase() {
  console.log('🧪 Running database tests...');
  try {
    const { testDatabaseOperations } = await import('./test');
    return await testDatabaseOperations();
  } catch (error) {
    console.error('❌ Database tests failed:', error);
    return false;
  }
}

async function showStats() {
  try {
    const stats = await databaseService.getCacheStats();
    console.log('📊 Database Statistics:', stats);
  } catch (error) {
    console.error('❌ Failed to get stats:', error);
  }
}

async function clearDatabase() {
  try {
    await databaseService.clearAllCaches();
    console.log('🧹 Database cleared successfully');
  } catch (error) {
    console.error('❌ Failed to clear database:', error);
  }
}

// Expose utilities to window object for manual testing
if (typeof window !== 'undefined') {
  window.inspectDB = {
    init: initDatabase,
    test: testDatabase,
    stats: showStats,
    clear: clearDatabase
  };

  console.log('🚀 Database testing utilities loaded. Usage:');
  console.log('  window.inspectDB.init("/path/to/logs") - Initialize database');
  console.log('  window.inspectDB.test() - Run tests');
  console.log('  window.inspectDB.stats() - Show cache statistics');
  console.log('  window.inspectDB.clear() - Clear all cached data');
}