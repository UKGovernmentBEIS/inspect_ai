import {
  ColumnFiltersState,
  ColumnResizeMode,
  SortingState,
} from "@tanstack/react-table";
import { EvalSet } from "../@types/log";
import { LogsState } from "../app/types";
import { EvalHeader, LogFile, LogSummary } from "../client/api/types";
import { DatabaseService } from "../client/database";
import { createLogger } from "../utils/logger";
import { StoreState } from "./store";

const log = createLogger("Log Slice");

export interface LogsSlice {
  logs: LogsState;
  logsActions: {
    // Update State
    setLogDir: (logDir?: string) => void;
    setLogFiles: (logFiles: LogFile[]) => void;

    updateLogOverview: (overviews: Record<string, LogSummary>) => void;

    syncLogOverviews: (logs: LogFile[]) => Promise<LogSummary[]>;
    setLogOverviewsLoading: (loading: boolean) => void;

    setSelectedLogIndex: (index: number) => void;
    setSelectedLogFile: (logUrl: string) => void;

    // Fetch or update logs
    syncLogs: () => Promise<void>;
    selectLogFile: (logUrl: string) => Promise<void>;

    // Cross-file sample operations
    getAllCachedSamples: () => Promise<any[]>;
    queryCachedSamples: (filter?: {
      completed?: boolean;
      hasError?: boolean;
      scoreRange?: { min: number; max: number; scoreName?: string };
    }) => Promise<any[]>;

    // Try to fetch an eval-set
    syncEvalSetInfo: (logPath?: string) => Promise<EvalSet | undefined>;

    setSorting: (sorting: SortingState) => void;
    setFiltering: (filtering: ColumnFiltersState) => void;
    setGlobalFilter: (globalFilter: string) => void;
    setColumnResizeMode: (mode: ColumnResizeMode) => void;
    setColumnSize: (columnId: string, size: number) => void;
    setFilteredCount: (count: number) => void;
    setWatchedLogs: (logs: LogFile[]) => void;
    clearWatchedLogs: () => void;
    setSelectedRowIndex: (index: number | null) => void;
  };
}

const initialState: LogsState = {
  logDir: undefined,
  logFiles: [],
  logOverviews: {},
  logOverviewsLoading: false,
  selectedLogIndex: -1,
  selectedLogFile: undefined as string | undefined,
  listing: {},
  loadingFiles: new Set<string>(),
  pendingRequests: new Map<string, Promise<EvalHeader | null>>(),
};

export const createLogsSlice = (
  set: (fn: (state: StoreState) => void) => void,
  get: () => StoreState,
  _store: any,
): [LogsSlice, () => void] => {
  const slice = {
    // State
    logs: initialState,

    // Actions
    logsActions: {
      setLogDir: (logDir?: string) =>
        set((state) => {
          state.logs.logDir = logDir;
        }),
      setLogFiles: (logFiles: LogFile[]) =>
        set((state) => {
          state.logs.logFiles = logFiles;
          state.logs.selectedLogFile =
            state.logs.selectedLogIndex > -1
              ? logFiles[state.logs.selectedLogIndex]?.name
              : undefined;
        }),
      syncLogOverviews: async (logs: LogFile[]) => {
        const state = get();
        const api = state.api;
        if (!api) {
          console.error("API not initialized in LogsStore");
          return [];
        }

        const filePaths = logs.map((log) => log.name);

        // OPTIONAL: Try cache first (non-blocking, fail silently)
        let cached: Record<string, LogSummary> = {};
        const databaseService = get().databaseService;
        if (databaseService) {
          try {
            cached = await databaseService.getCachedLogSummaries(filePaths);
          } catch (e) {
            // Cache read failed, continue with normal flow
          }
        }

        // Filter out files that are already loaded, cached, or currently loading
        // reload headers with "started" status as they may have changed
        const filesToLoad = logs.filter((logFile) => {
          const existing = state.logs.logOverviews[logFile.name];
          const cachedOverview = cached[logFile.name];
          const isLoading = state.logs.loadingFiles.has(logFile.name);

          // Use cached version if available and not "started"
          if (cachedOverview && cachedOverview.status !== "started") {
            return false;
          }

          // Always load if no existing header and no cached version
          if (!existing && !cachedOverview) {
            return !isLoading;
          }

          // Reload if header status is "started" or "error" (but not if already loading)
          const overview = existing || cachedOverview;
          if (overview && overview.status === "started") {
            return !isLoading;
          }

          // Skip if already loaded with final status
          return false;
        });

        // Include cached overviews in the store immediately
        if (Object.keys(cached).length > 0) {
          set((state) => {
            state.logs.logOverviews = {
              ...state.logs.logOverviews,
              ...cached,
            };
          });
        }

        if (filesToLoad.length === 0) {
          return Object.values({ ...state.logs.logOverviews, ...cached });
        }

        // Mark files as loading
        set((state) => {
          filesToLoad.forEach((logFile) => {
            state.logs.loadingFiles.add(logFile.name);
          });
        });

        // Set global loading state if this is the first batch
        set((state) => {
          state.logs.logOverviewsLoading = true;
        });

        try {
          log.debug(
            `LOADING LOG OVERVIEWS from API for ${filesToLoad.length} files`,
          );
          const headers = await api.get_log_summaries(
            filesToLoad.map((log) => log.name),
          );

          // Process results and update store
          const headerMap: Record<string, LogSummary> = {};
          for (let i = 0; i < filesToLoad.length; i++) {
            const logFile = filesToLoad[i];
            const header = headers[i];
            if (header) {
              headerMap[logFile.name] = header as LogSummary;
            }
          }

          // Update headers in store
          set((state) => {
            state.logs.logOverviews = {
              ...state.logs.logOverviews,
              ...headerMap,
            };
            // Remove from loading state
            filesToLoad.forEach((logFile) => {
              state.logs.loadingFiles.delete(logFile.name);
            });
            // Update global loading state if no more files are loading
            state.logs.logOverviewsLoading = false;
          });

          // OPTIONAL: Cache log summaries (non-blocking)
          if (databaseService && Object.keys(headerMap).length > 0) {
            setTimeout(() => {
              databaseService
                .cacheLogSummaries(
                  Object.values(headerMap),
                  Object.keys(headerMap),
                )
                .catch(() => {
                  // Silently ignore cache errors
                });
            }, 0);
          }

          return Object.values({ ...cached, ...headerMap });
        } catch (error) {
          log.error("Error loading log headers", error);

          // Clear loading state on error
          set((state) => {
            filesToLoad.forEach((logFile) => {
              state.logs.loadingFiles.delete(logFile.name);
            });
            state.logs.logOverviewsLoading = false;
          });

          // Still return cached overviews if we have them
          if (Object.keys(cached).length > 0) {
            return Object.values(cached);
          }

          // Don't throw - just return empty array like the old implementation
          return [];
        }
      },
      setLogOverviewsLoading: (loading: boolean) =>
        set((state) => {
          state.logs.logOverviewsLoading = loading;
        }),
      setSelectedLogIndex: (selectedLogIndex: number) => {
        set((state) => {
          state.logs.selectedLogIndex = selectedLogIndex;
          const file = state.logs.logFiles[selectedLogIndex];
          state.logs.selectedLogFile = file ? file.name : undefined;
        });
      },
      updateLogOverview: (overviews: Record<string, LogSummary>) =>
        set((state) => {
          // TODO: write through to the database
          state.logs.logOverviews = {
            ...get().logs.logOverviews,
            ...overviews,
          };
        }),

      setSelectedLogFile: (logUrl: string) => {
        const state = get();
        const index = state.logs.logFiles.findIndex((val: { name: string }) =>
          logUrl.endsWith(val.name),
        );

        if (index > -1) {
          state.logsActions.setSelectedLogIndex(index);
          state.logs.selectedLogFile =
            state.logs.logFiles[index]?.name ?? undefined;
        }
      },
      syncLogs: async () => {
        const api = get().api;
        if (!api) {
          console.error("API not initialized in LogsStore");
          return;
        }

        // Determine the log directory
        const loadLogDir = async () => {
          try {
            return await api.get_log_dir();
          } catch (e) {
            console.log(e);
            get().appActions.setStatus({ loading: false, error: e as Error });
            return undefined;
          }
        };
        const logDir = await loadLogDir();
        get().logsActions.setLogDir(logDir);

        // Initialize the database
        const initializeDatabase = async (
          logDir?: string,
        ): Promise<DatabaseService | undefined> => {
          if (!logDir) {
            // No database service available
            return undefined;
          }

          try {
            const databaseService = get().databaseService;
            if (!databaseService) {
              return undefined;
            }
            await databaseService.openDatabase(logDir);
            return databaseService;
          } catch (e) {
            console.log(e);
            get().appActions.setStatus({ loading: false, error: e as Error });
          }
        };

        // Activate the database for this log directory
        const databaseService = await initializeDatabase(logDir);

        // Read the cached values
        let cached;
        if (databaseService) {
          try {
            cached = await databaseService.getCachedLogFiles();
            if (cached && cached.length > 0) {
              log.debug("LOADED LOG FILES FROM CACHE");
              // Activate the current log files
              get().logsActions.setLogFiles(cached);
            }
          } catch (e) {
            // Cache read failed, use API results we already have
          }
        }

        // What is our most recent known log file and total count?
        let mtime = 0;
        if (cached && cached.length > 0) {
          mtime = Math.max(...cached.map((file) => file.mtime || 0));
        }

        // Now query the server and update the store with fresh data
        log.debug("LOADING LOG FILES FROM API");
        const files = await api.get_log_files(mtime);

        // Cache the result we got from API
        setTimeout(() => {
          if (databaseService) {
            databaseService.cacheLogFiles(files).catch(() => {
              // Silently ignore cache errors
            });
            const state = get();
            const currentLog =
              state.logs.selectedLogIndex > -1
                ? state.logs.logFiles[state.logs.selectedLogIndex]
                : undefined;

            get().logsActions.setLogFiles(files);

            if (currentLog) {
              const newIndex = files.findIndex((file) =>
                currentLog.name.endsWith(file.name),
              );

              if (newIndex !== undefined && newIndex !== -1) {
                state.logsActions.setSelectedLogIndex(newIndex);
              }
            }
          }
        }, 0);
      },
      syncEvalSetInfo: async (logPath?: string) => {
        const api = get().api;
        if (!api) {
          console.error("API not initialized in LogsStore");
          return undefined;
        }
        const info = await api.get_eval_set(logPath);
        set((state) => {
          state.logs.evalSet = info;
        });
      },
      // Select a specific log file
      selectLogFile: async (logUrl: string) => {
        const state = get();
        const index = state.logs.logFiles.findIndex((val: { name: string }) =>
          val.name.endsWith(logUrl),
        );

        // It is already loaded
        if (index > -1) {
          state.logsActions.setSelectedLogIndex(index);
        }
      },
      setSorting: (sorting: SortingState) => {
        set((state) => {
          state.logs.listing.sorting = sorting;
        });
      },
      setFiltering: (filtering: ColumnFiltersState) => {
        set((state) => {
          state.logs.listing.filtering = filtering;
        });
      },
      setGlobalFilter: (globalFilter: string) => {
        set((state) => {
          state.logs.listing.globalFilter = globalFilter;
        });
      },
      setColumnResizeMode: (mode: ColumnResizeMode) => {
        set((state) => {
          state.logs.listing.columnResizeMode = mode;
        });
      },
      setColumnSize: (columnId: string, size: number) => {
        set((state) => {
          if (!state.logs.listing.columnSizes) {
            state.logs.listing.columnSizes = {};
          }
          state.logs.listing.columnSizes[columnId] = size;
        });
      },
      setFilteredCount: (count: number) => {
        set((state) => {
          state.logs.listing.filteredCount = count;
        });
      },
      setWatchedLogs: (logs: LogFile[]) => {
        set((state) => {
          state.logs.listing.watchedLogs = logs;
        });
      },
      clearWatchedLogs: () => {
        set((state) => {
          state.logs.listing.watchedLogs = undefined;
        });
      },
      setSelectedRowIndex: (index: number | null) => {
        set((state) => {
          state.logs.listing.selectedRowIndex = index;
        });
      },
      // Cross-file sample operations
      getAllCachedSamples: async () => {
        try {
          log.debug("LOADING ALL CACHED SAMPLES");
          const dbService = get().databaseService;
          if (!dbService) {
            throw new Error("Database service not initialized");
          }
          const samples = await dbService.getAllSampleSummaries();
          log.debug(`Retrieved ${samples.length} cached samples`);
          return samples;
        } catch (e) {
          log.debug("No cached samples available");
          return [];
        }
      },

      queryCachedSamples: async (filter?: {
        completed?: boolean;
        hasError?: boolean;
        scoreRange?: { min: number; max: number; scoreName?: string };
      }) => {
        try {
          log.debug("QUERYING CACHED SAMPLES", filter);
          const dbService = get().databaseService;
          if (!dbService) {
            throw new Error("Database service not initialized");
          }
          const samples = await dbService.querySampleSummaries(filter);
          log.debug(`Query returned ${samples.length} samples`);
          return samples;
        } catch (e) {
          log.debug("Sample query failed, returning empty results");
          return [];
        }
      },
    },
  } as const;

  const cleanup = () => {
    // Database cleanup is handled in the main store cleanup
  };

  return [slice, cleanup];
};

export const initializeLogsSlice = <T extends LogsSlice>(
  set: (fn: (state: T) => void) => void,
) => {
  set((state) => {
    if (!state.logs) {
      state.logs = initialState;
    }
  });
};
