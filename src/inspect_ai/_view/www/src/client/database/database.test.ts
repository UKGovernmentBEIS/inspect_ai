/**
 * Automated tests for database functionality
 * Uses fake-indexeddb for testing IndexedDB operations in Jest
 *
 * Schema v3 structure:
 * - log_files: stores results from get_log_files()
 * - log_summaries: stores results from get_log_summaries()
 * - log_info: stores complete results from get_log_info() including samples
 */

import { LogInfo, LogRoot, LogSummary, SampleSummary } from "../api/types";
import { createDatabaseService, DatabaseService } from "./service";

// Helper function to create test LogSummary
function createTestLogSummary(overrides: Partial<LogSummary> = {}): LogSummary {
  return {
    eval_id: "eval-1",
    run_id: "run-1",
    task: "test-task",
    task_id: "task-1",
    task_version: 1,
    version: 1,
    status: "success",
    error: null,
    model: "gpt-4",
    started_at: "2024-01-01T00:00:00Z",
    completed_at: "2024-01-01T01:00:00Z",
    ...overrides,
  } as LogSummary;
}

// Helper function to create test LogInfo
function createTestLogInfo(overrides: Partial<LogInfo> = {}): LogInfo {
  return {
    version: 1,
    status: "success",
    eval: {
      eval_set_id: "set-1",
      eval_id: "eval-1",
      run_id: "run-1",
      created: "2024-01-01T00:00:00Z",
      task: "test-task",
      task_id: "task-1",
      task_version: 1,
      task_file: "test.py",
      task_display_name: "Test Task",
      task_registry_name: "test",
      task_attribs: {},
      task_args: {},
      task_args_passed: {},
      solver: null,
      solver_args: {},
      tags: [],
      dataset: {
        name: "test-dataset",
        location: "/test/dataset",
        samples: 10,
        sample_ids: ["1", "2", "3"],
        shuffled: false,
      },
      sandbox: null,
      model: "gpt-4",
      model_generate_config: {} as any,
      model_base_url: null,
    } as any,
    plan: undefined,
    results: null,
    stats: undefined,
    error: null,
    sampleSummaries: [],
    ...overrides,
  };
}

// Helper function to create test SampleSummary
function createTestSampleSummary(
  overrides: Partial<SampleSummary> = {},
): SampleSummary {
  return {
    id: 1,
    epoch: 0,
    input: "test input",
    target: "test target",
    scores: {
      accuracy: {
        value: 0.9,
        answer: null,
        explanation: null,
        metadata: {},
        history: [],
      },
    },
    completed: true,
    ...overrides,
  } as SampleSummary;
}

describe("Database Service", () => {
  let databaseService: DatabaseService;

  beforeEach(async () => {
    // Create a new database service for each test
    databaseService = createDatabaseService();
    // Open database with test log directory
    await databaseService.openDatabase("/test/logs");
  });

  afterEach(async () => {
    // Clean up after each test (only if database is still open)
    try {
      await databaseService.clearAllCaches();
      await databaseService.closeDatabase();
    } catch {
      // Database might already be closed in error handling tests
    }
  });

  describe("Log Files Caching", () => {
    test("should cache and retrieve log files", async () => {
      const testLogRoot: LogRoot = {
        log_dir: "/test/logs",
        files: [
          {
            name: "/test/logs/eval1.json",
            task: "test-task-1",
            task_id: "task1",
          },
          {
            name: "/test/logs/eval2.json",
            task: "test-task-2",
            task_id: "task2",
          },
        ],
      };

      // Cache the log files
      await databaseService.cacheLogFiles(testLogRoot);

      // Retrieve cached files
      const cached = await databaseService.getCachedLogFiles();

      expect(cached).not.toBeNull();
      expect(cached?.files).toHaveLength(2);
      expect(cached?.files[0].name).toBe("/test/logs/eval1.json");
      expect(cached?.files[0].task).toBe("test-task-1");
    });

    test("should update existing cached log files", async () => {
      const initialLogRoot: LogRoot = {
        log_dir: "/test/logs",
        files: [{ name: "/test/logs/eval1.json", task: "initial-task" }],
      };

      await databaseService.cacheLogFiles(initialLogRoot);

      // Update with new data
      const updatedLogRoot: LogRoot = {
        log_dir: "/test/logs",
        files: [
          { name: "/test/logs/eval1.json", task: "updated-task" },
          { name: "/test/logs/eval2.json", task: "additional-task" },
        ],
      };

      await databaseService.cacheLogFiles(updatedLogRoot);

      const cached = await databaseService.getCachedLogFiles();
      expect(cached?.files).toHaveLength(2);
      expect(
        cached?.files.find((f) => f.name === "/test/logs/eval1.json")?.task,
      ).toBe("updated-task");
      expect(
        cached?.files.find((f) => f.name === "/test/logs/eval2.json")?.task,
      ).toBe("additional-task");
    });
  });

  describe("Log Summaries Caching", () => {
    test("should cache and retrieve log summaries", async () => {
      const summaries = [
        createTestLogSummary({ eval_id: "eval-1", task: "task-1" }),
        createTestLogSummary({ eval_id: "eval-2", task: "task-2" }),
      ];
      const filePaths = ["/test/logs/eval1.json", "/test/logs/eval2.json"];

      // Cache the summaries
      await databaseService.cacheLogSummaries(summaries, filePaths);

      // Retrieve cached summaries
      const cached = await databaseService.getCachedLogSummaries(filePaths);

      expect(Object.keys(cached)).toHaveLength(2);
      expect(cached["/test/logs/eval1.json"]).toBeDefined();
      expect(cached["/test/logs/eval1.json"].eval_id).toBe("eval-1");
      expect(cached["/test/logs/eval2.json"].task).toBe("task-2");
    });

    test("should handle partial cache hits", async () => {
      const summary = createTestLogSummary({ eval_id: "eval-1" });

      // Cache only one summary
      await databaseService.cacheLogSummaries(
        [summary],
        ["/test/logs/eval1.json"],
      );

      // Request multiple summaries
      const cached = await databaseService.getCachedLogSummaries([
        "/test/logs/eval1.json",
        "/test/logs/eval2.json",
        "/test/logs/eval3.json",
      ]);

      // Should only return the cached one
      expect(Object.keys(cached)).toHaveLength(1);
      expect(cached["/test/logs/eval1.json"]).toBeDefined();
      expect(cached["/test/logs/eval2.json"]).toBeUndefined();
    });
  });

  describe("Log Info Caching", () => {
    test("should cache and retrieve log info with samples", async () => {
      const samples = [
        createTestSampleSummary({ id: 1 }),
        createTestSampleSummary({
          id: 2,
          scores: {
            accuracy: {
              value: 0.85,
              answer: null,
              explanation: null,
              metadata: {},
              history: [],
            },
          },
        }),
      ];

      const logInfo = createTestLogInfo({
        sampleSummaries: samples,
      });

      // Cache the log info
      await databaseService.cacheLogInfo("/test/logs/eval1.json", logInfo);

      // Retrieve cached log info
      const cached = await databaseService.getCachedLogInfo(
        "/test/logs/eval1.json",
      );

      expect(cached).not.toBeNull();
      expect(cached?.eval.eval_id).toBe("eval-1");
      expect(cached?.sampleSummaries).toHaveLength(2);
      expect(cached?.sampleSummaries[0].id).toBe(1);
    });

    test("should return null for non-cached log info", async () => {
      const cached = await databaseService.getCachedLogInfo(
        "/test/logs/nonexistent.json",
      );
      expect(cached).toBeNull();
    });
  });

  describe("Sample Summaries Extraction", () => {
    test("should extract sample summaries from cached log info", async () => {
      const samples = [
        createTestSampleSummary({ id: 1, completed: true }),
        createTestSampleSummary({ id: 2, completed: false }),
        createTestSampleSummary({ id: 3, error: "timeout" }),
      ];

      const logInfo = createTestLogInfo({
        sampleSummaries: samples,
      });

      // Cache the log info
      await databaseService.cacheLogInfo("/test/logs/eval1.json", logInfo);

      // Get samples for the file
      const retrievedSamples = await databaseService.getSampleSummariesForFile(
        "/test/logs/eval1.json",
      );

      expect(retrievedSamples).toHaveLength(3);
      expect(retrievedSamples[0].id).toBe(1);
      expect(retrievedSamples[1].completed).toBe(false);
      expect(retrievedSamples[2].error).toBe("timeout");
    });

    test("should return empty array for file without cached info", async () => {
      const samples = await databaseService.getSampleSummariesForFile(
        "/test/logs/nonexistent.json",
      );
      expect(samples).toEqual([]);
    });

    test("should get all sample summaries across multiple files", async () => {
      const logInfo1 = createTestLogInfo({
        sampleSummaries: [
          createTestSampleSummary({ id: 1 }),
          createTestSampleSummary({ id: 2 }),
        ],
      });

      const logInfo2 = createTestLogInfo({
        sampleSummaries: [createTestSampleSummary({ id: 3 })],
      });

      await databaseService.cacheLogInfo("/test/logs/eval1.json", logInfo1);
      await databaseService.cacheLogInfo("/test/logs/eval2.json", logInfo2);

      const allSamples = await databaseService.getAllSampleSummaries();
      expect(allSamples).toHaveLength(3);
    });

    test("should query sample summaries with filters", async () => {
      const samples = [
        createTestSampleSummary({ id: 1, completed: true }),
        createTestSampleSummary({
          id: 2,
          completed: false,
          scores: {
            accuracy: {
              value: 0.7,
              answer: null,
              explanation: null,
              metadata: {},
              history: [],
            },
          },
        }),
        createTestSampleSummary({
          id: 3,
          completed: true,
          error: "timeout",
          scores: {
            accuracy: {
              value: 0.8,
              answer: null,
              explanation: null,
              metadata: {},
              history: [],
            },
          },
        }),
        createTestSampleSummary({
          id: 4,
          completed: true,
          scores: {
            accuracy: {
              value: 0.6,
              answer: null,
              explanation: null,
              metadata: {},
              history: [],
            },
          },
        }),
      ];

      const logInfo = createTestLogInfo({ sampleSummaries: samples });
      await databaseService.cacheLogInfo("/test/logs/eval1.json", logInfo);

      // Test completed filter
      const completedSamples = await databaseService.querySampleSummaries({
        completed: true,
      });
      expect(completedSamples).toHaveLength(3);

      // Test error filter
      const errorSamples = await databaseService.querySampleSummaries({
        hasError: true,
      });
      expect(errorSamples).toHaveLength(1);
      expect(errorSamples[0].id).toBe(3);

      // Test score range filter
      const highScoreSamples = await databaseService.querySampleSummaries({
        scoreRange: { min: 0.8, max: 1.0, scoreName: "accuracy" },
      });
      expect(highScoreSamples).toHaveLength(2);
      expect(highScoreSamples[0].id).toBe(1);
      expect(highScoreSamples[1].id).toBe(3);
    });
  });

  describe("Cache Statistics and Management", () => {
    test("should return cache statistics", async () => {
      const stats = await databaseService.getCacheStats();

      expect(stats.logFiles).toBe(0);
      expect(stats.logSummaries).toBe(0);
      expect(stats.sampleSummaries).toBe(0);
      expect(stats.logDir).toBe("/test/logs");
    });

    test("should clear all caches", async () => {
      // Cache data in all tables
      await databaseService.cacheLogFiles({
        log_dir: "/test/logs",
        files: [
          { name: "/test/logs/eval1.json", task: "task-1", task_id: "task1" },
        ],
      });

      await databaseService.cacheLogSummaries(
        [createTestLogSummary()],
        ["/test/logs/eval1.json"],
      );

      await databaseService.cacheLogInfo(
        "/test/logs/eval1.json",
        createTestLogInfo({
          sampleSummaries: [createTestSampleSummary()],
        }),
      );

      const stats1 = await databaseService.getCacheStats();
      expect(stats1.logFiles).toBe(1);
      expect(stats1.logSummaries).toBe(1);
      expect(stats1.sampleSummaries).toBe(1);

      // Clear all caches
      await databaseService.clearAllCaches();

      const stats2 = await databaseService.getCacheStats();
      expect(stats2.logFiles).toBe(0);
      expect(stats2.logSummaries).toBe(0);
      expect(stats2.sampleSummaries).toBe(0);
    });

    test("should count sample summaries correctly", async () => {
      // Cache multiple log info with different number of samples
      await databaseService.cacheLogInfo(
        "/test/logs/eval1.json",
        createTestLogInfo({
          sampleSummaries: [
            createTestSampleSummary({ id: 1 }),
            createTestSampleSummary({ id: 2 }),
          ],
        }),
      );

      await databaseService.cacheLogInfo(
        "/test/logs/eval2.json",
        createTestLogInfo({
          sampleSummaries: [
            createTestSampleSummary({ id: 3 }),
            createTestSampleSummary({ id: 4 }),
            createTestSampleSummary({ id: 5 }),
          ],
        }),
      );

      const stats = await databaseService.getCacheStats();
      expect(stats.sampleSummaries).toBe(5); // Total samples across both files
    });
  });

  describe("Error Handling", () => {
    test("should handle cache retrieval errors gracefully", async () => {
      // Close database to simulate error
      await databaseService.closeDatabase();

      // Should return null when database is closed (graceful error handling)
      const result = await databaseService.getCachedLogFiles();
      expect(result).toBeNull();
    });
  });
});
