export { AppDatabase } from './schema';
export type {
  LogFileRecord,
  LogSummaryRecord,
  LogHeaderRecord,
  SampleSummaryRecord
} from './schema';

export { databaseManager } from './manager';
export { databaseService, DatabaseService } from './service';
export { testDatabaseOperations } from './test';

// Import manual test utilities (adds window.inspectDB)
import './manual-test';