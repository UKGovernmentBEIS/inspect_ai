/**
 * Automated tests for database functionality
 * Uses fake-indexeddb for testing IndexedDB operations in Jest
 */

import { databaseService } from './service';
import { LogFiles, LogOverview, SampleSummary } from '../api/types';

describe('Database Service', () => {
  beforeEach(async () => {
    // Initialize with test log directory
    await databaseService.switchLogDir('/test/logs');
  });

  afterEach(async () => {
    // Clean up after each test
    await databaseService.clearAllCaches();
  });

  describe('Log Files Caching', () => {
    test('should cache and retrieve log files', async () => {
      const testLogFiles: LogFiles = {
        log_dir: '/test/logs',
        files: [
          { name: '/test/logs/eval1.json', task: 'test-task-1', task_id: 'task1' },
          { name: '/test/logs/eval2.json', task: 'test-task-2', task_id: 'task2' }
        ]
      };

      // Cache the files
      await databaseService.cacheLogFiles(testLogFiles);

      // Retrieve from cache
      const cached = await databaseService.getCachedLogFiles();

      expect(cached).not.toBeNull();
      expect(cached!.files).toHaveLength(2);
      expect(cached!.files[0].name).toBe('/test/logs/eval1.json');
      expect(cached!.files[0].task).toBe('test-task-1');
    });

    test('should handle empty log files', async () => {
      const emptyLogFiles: LogFiles = {
        log_dir: '/test/logs',
        files: []
      };

      await databaseService.cacheLogFiles(emptyLogFiles);
      const cached = await databaseService.getCachedLogFiles();

      expect(cached).not.toBeNull();
      expect(cached!.files).toHaveLength(0);
    });

    test('should update existing log files (upsert)', async () => {
      const initialFiles: LogFiles = {
        log_dir: '/test/logs',
        files: [
          { name: '/test/logs/eval1.json', task: 'old-task', task_id: 'old_id' }
        ]
      };

      const updatedFiles: LogFiles = {
        log_dir: '/test/logs',
        files: [
          { name: '/test/logs/eval1.json', task: 'new-task', task_id: 'new_id' },
          { name: '/test/logs/eval2.json', task: 'additional-task', task_id: 'add_id' }
        ]
      };

      // Cache initial files
      await databaseService.cacheLogFiles(initialFiles);
      let cached = await databaseService.getCachedLogFiles();
      expect(cached!.files).toHaveLength(1);

      // Cache updated files (should upsert)
      await databaseService.cacheLogFiles(updatedFiles);
      cached = await databaseService.getCachedLogFiles();

      expect(cached!.files).toHaveLength(2);
      expect(cached!.files.find(f => f.name === '/test/logs/eval1.json')?.task).toBe('new-task');
      expect(cached!.files.find(f => f.name === '/test/logs/eval2.json')?.task).toBe('additional-task');
    });
  });

  describe('Log Summaries Caching', () => {
    test('should cache and retrieve log summaries', async () => {
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
      const cached = await databaseService.getCachedLogSummaries(['/test/logs/eval1.json']);

      expect(cached['/test/logs/eval1.json']).toBeDefined();
      expect(cached['/test/logs/eval1.json'].eval_id).toBe('eval-1');
      expect(cached['/test/logs/eval1.json'].model).toBe('gpt-4');
    });

    test('should handle multiple log summaries', async () => {
      const testSummaries: Record<string, LogOverview> = {
        '/test/logs/eval1.json': {
          eval_id: 'eval-1',
          run_id: 'run-1',
          task: 'task-1',
          task_id: 'task1',
          task_version: 1,
          model: 'gpt-4',
          status: 'success',
          started_at: '2024-01-01T00:00:00Z',
          completed_at: '2024-01-01T01:00:00Z'
        },
        '/test/logs/eval2.json': {
          eval_id: 'eval-2',
          run_id: 'run-2',
          task: 'task-2',
          task_id: 'task2',
          task_version: 1,
          model: 'claude-3',
          status: 'started',
          started_at: '2024-01-01T02:00:00Z'
        }
      };

      await databaseService.cacheLogSummaries(testSummaries);
      const cached = await databaseService.getCachedLogSummaries([
        '/test/logs/eval1.json',
        '/test/logs/eval2.json'
      ]);

      expect(Object.keys(cached)).toHaveLength(2);
      expect(cached['/test/logs/eval1.json'].status).toBe('success');
      expect(cached['/test/logs/eval2.json'].status).toBe('started');
    });
  });

  describe('Sample Summaries Caching', () => {
    test('should cache and retrieve sample summaries', async () => {
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
      const cached = await databaseService.getSampleSummariesForFile('/test/logs/eval1.json');

      expect(cached).toHaveLength(2);
      expect(cached[0].id).toBe('sample-1');
      expect(cached[1].id).toBe('sample-2');
      expect(cached[0].scores.accuracy.value).toBe(0.85);
    });

    test('should handle cross-file sample queries', async () => {
      const samples1: SampleSummary[] = [
        {
          id: 'sample-1',
          epoch: 1,
          input: 'Input 1',
          target: 'Target 1',
          scores: { accuracy: { value: 0.85, answer: null, explanation: null, metadata: {} } },
          completed: true
        }
      ];

      const samples2: SampleSummary[] = [
        {
          id: 'sample-2',
          epoch: 1,
          input: 'Input 2',
          target: 'Target 2',
          scores: { accuracy: { value: 0.95, answer: null, explanation: null, metadata: {} } },
          completed: true
        }
      ];

      // Cache samples from different files
      await databaseService.cacheSampleSummaries('/test/logs/eval1.json', samples1);
      await databaseService.cacheSampleSummaries('/test/logs/eval2.json', samples2);

      // Query all samples across files
      const allSamples = await databaseService.getAllSampleSummaries();
      expect(allSamples).toHaveLength(2);

      // Query with filters
      const highScoreSamples = await databaseService.querySampleSummaries({
        scoreRange: { min: 0.9, max: 1.0 }
      });
      expect(highScoreSamples).toHaveLength(1);
      expect(highScoreSamples[0].id).toBe('sample-2');
    });

    test('should handle compound primary key updates', async () => {
      const initialSample: SampleSummary[] = [
        {
          id: 'sample-1',
          epoch: 1,
          input: 'Initial input',
          target: 'Initial target',
          scores: { accuracy: { value: 0.5, answer: null, explanation: null, metadata: {} } },
          completed: false
        }
      ];

      const updatedSample: SampleSummary[] = [
        {
          id: 'sample-1',
          epoch: 1,
          input: 'Updated input',
          target: 'Updated target',
          scores: { accuracy: { value: 0.9, answer: null, explanation: null, metadata: {} } },
          completed: true
        }
      ];

      // Cache initial sample
      await databaseService.cacheSampleSummaries('/test/logs/eval1.json', initialSample);
      let cached = await databaseService.getSampleSummariesForFile('/test/logs/eval1.json');
      expect(cached).toHaveLength(1);
      expect(cached[0].completed).toBe(false);

      // Update the same sample (same file_path + sample_id + epoch)
      await databaseService.cacheSampleSummaries('/test/logs/eval1.json', updatedSample);
      cached = await databaseService.getSampleSummariesForFile('/test/logs/eval1.json');

      expect(cached).toHaveLength(1); // Should still be 1, not 2
      expect(cached[0].completed).toBe(true); // Should be updated
      expect(cached[0].input).toBe('Updated input');
      expect(cached[0].scores.accuracy.value).toBe(0.9);
    });
  });

  describe('Cache Statistics and Management', () => {
    test('should provide accurate cache statistics', async () => {
      // Add some test data
      const logFiles: LogFiles = {
        log_dir: '/test/logs',
        files: [
          { name: '/test/logs/eval1.json', task: 'task1', task_id: 'id1' },
          { name: '/test/logs/eval2.json', task: 'task2', task_id: 'id2' }
        ]
      };

      const logSummaries: Record<string, LogOverview> = {
        '/test/logs/eval1.json': {
          eval_id: 'eval-1',
          run_id: 'run-1',
          task: 'task1',
          task_id: 'id1',
          task_version: 1,
          model: 'gpt-4',
          status: 'success',
          started_at: '2024-01-01T00:00:00Z',
          completed_at: '2024-01-01T01:00:00Z'
        }
      };

      const sampleSummaries: SampleSummary[] = [
        {
          id: 'sample-1',
          epoch: 1,
          input: 'Input',
          target: 'Target',
          scores: { accuracy: { value: 0.85, answer: null, explanation: null, metadata: {} } },
          completed: true
        }
      ];

      await databaseService.cacheLogFiles(logFiles);
      await databaseService.cacheLogSummaries(logSummaries);
      await databaseService.cacheSampleSummaries('/test/logs/eval1.json', sampleSummaries);

      const stats = await databaseService.getCacheStats();

      expect(stats.logFiles).toBe(2);
      expect(stats.logSummaries).toBe(1);
      expect(stats.sampleSummaries).toBe(1);
      expect(stats.logDir).toBe('/test/logs');
    });

    test('should clear all caches', async () => {
      // Add test data
      const logFiles: LogFiles = {
        log_dir: '/test/logs',
        files: [{ name: '/test/logs/eval1.json', task: 'task1', task_id: 'id1' }]
      };

      await databaseService.cacheLogFiles(logFiles);

      // Verify data exists
      let stats = await databaseService.getCacheStats();
      expect(stats.logFiles).toBe(1);

      // Clear all caches
      await databaseService.clearAllCaches();

      // Verify data is cleared
      stats = await databaseService.getCacheStats();
      expect(stats.logFiles).toBe(0);
      expect(stats.logSummaries).toBe(0);
      expect(stats.sampleSummaries).toBe(0);
    });
  });

  describe('Error Handling', () => {
    test('should handle database errors gracefully', async () => {
      // This test ensures the service handles database errors without crashing
      // In a real scenario, we might simulate database failures

      const result = await databaseService.getCachedLogFiles();
      expect(result).toBeDefined(); // Should not throw
    });

    test('should handle empty query results', async () => {
      const cached = await databaseService.getCachedLogSummaries(['/nonexistent/file.json']);
      expect(cached).toEqual({});

      const samples = await databaseService.getSampleSummariesForFile('/nonexistent/file.json');
      expect(samples).toEqual([]);
    });
  });
});