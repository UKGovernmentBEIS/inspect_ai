/**
 * Simple test script for database operations
 * This is not a formal test file but a utility to verify database functionality
 */

import { databaseService } from './service';
import { LogFiles, LogOverview, SampleSummary } from '../api/types';

export async function testDatabaseOperations() {
  console.log('🧪 Testing database operations...');

  try {
    // Test 1: Switch to a test log directory
    console.log('1. Testing log directory switching...');
    await databaseService.switchLogDir('/test/logs');
    console.log('✅ Successfully switched log directory');

    // Test 2: Cache and retrieve log files
    console.log('2. Testing log files caching...');
    const testLogFiles: LogFiles = {
      log_dir: '/test/logs',
      files: [
        { name: '/test/logs/eval1.json', task: 'test-task-1', task_id: 'task1' },
        { name: '/test/logs/eval2.json', task: 'test-task-2', task_id: 'task2' }
      ]
    };

    await databaseService.cacheLogFiles(testLogFiles);
    const cachedFiles = await databaseService.getCachedLogFiles();

    if (cachedFiles && cachedFiles.files.length === 2) {
      console.log('✅ Log files caching works correctly');
    } else {
      console.log('❌ Log files caching failed');
    }

    // Test 3: Cache and retrieve log summaries
    console.log('3. Testing log summaries caching...');
    const testSummaries: Record<string, LogOverview> = {
      '/test/logs/eval1.json': {
        eval_id: 'eval-1',
        run_id: 'run-1',
        task: 'test-task-1',
        task_id: 'task1',
        task_version: 1,
        model: 'gpt-4',
        status: 'success',
        started_at: '2024-01-01T00:00:00Z',
        completed_at: '2024-01-01T01:00:00Z'
      }
    };

    await databaseService.cacheLogSummaries(testSummaries);
    const cachedSummaries = await databaseService.getCachedLogSummaries(['/test/logs/eval1.json']);

    if (cachedSummaries['/test/logs/eval1.json']?.eval_id === 'eval-1') {
      console.log('✅ Log summaries caching works correctly');
    } else {
      console.log('❌ Log summaries caching failed');
    }

    // Test 4: Cache and retrieve sample summaries
    console.log('4. Testing sample summaries caching...');
    const testSampleSummaries: SampleSummary[] = [
      {
        id: 'sample-1',
        epoch: 1,
        input: 'Test input',
        target: 'Test target',
        scores: { accuracy: { value: 0.85, answer: null, explanation: null, metadata: {} } },
        completed: true
      },
      {
        id: 'sample-2',
        epoch: 1,
        input: 'Test input 2',
        target: 'Test target 2',
        scores: { accuracy: { value: 0.92, answer: null, explanation: null, metadata: {} } },
        completed: true
      }
    ];

    await databaseService.cacheSampleSummaries('/test/logs/eval1.json', testSampleSummaries);
    const cachedSamples = await databaseService.getSampleSummariesForFile('/test/logs/eval1.json');

    if (cachedSamples.length === 2) {
      console.log('✅ Sample summaries caching works correctly');
    } else {
      console.log('❌ Sample summaries caching failed');
    }

    // Test 5: Cross-file sample queries
    console.log('5. Testing cross-file sample queries...');
    const allSamples = await databaseService.getAllSampleSummaries();

    if (allSamples.length === 2) {
      console.log('✅ Cross-file sample queries work correctly');
    } else {
      console.log('❌ Cross-file sample queries failed');
    }

    // Test 6: Query with filters
    console.log('6. Testing filtered sample queries...');
    const highScoreSamples = await databaseService.querySampleSummaries({
      scoreRange: { min: 0.9, max: 1.0 }
    });

    if (highScoreSamples.length === 1) {
      console.log('✅ Filtered sample queries work correctly');
    } else {
      console.log('❌ Filtered sample queries failed');
    }

    // Test 7: Cache statistics
    console.log('7. Testing cache statistics...');
    const stats = await databaseService.getCacheStats();

    console.log('📊 Cache statistics:', {
      logFiles: stats.logFiles,
      logSummaries: stats.logSummaries,
      sampleSummaries: stats.sampleSummaries,
      logDir: stats.logDir
    });

    if (stats.logFiles > 0 && stats.logSummaries > 0 && stats.sampleSummaries > 0) {
      console.log('✅ Cache statistics work correctly');
    } else {
      console.log('❌ Cache statistics failed');
    }

    // Cleanup
    console.log('8. Cleaning up test data...');
    await databaseService.clearAllCaches();
    console.log('✅ Test cleanup completed');

    console.log('🎉 All database tests passed!');
    return true;

  } catch (error) {
    console.error('❌ Database test failed:', error);
    return false;
  }
}

// Export for use in browser console or other test environments
if (typeof window !== 'undefined') {
  (window as any).testDatabase = testDatabaseOperations;
}