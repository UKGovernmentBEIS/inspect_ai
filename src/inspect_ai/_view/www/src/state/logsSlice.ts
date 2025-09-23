import {
  ColumnFiltersState,
  ColumnResizeMode,
  SortingState,
} from "@tanstack/react-table";
import { EvalSet } from "../@types/log";
import { LogsState } from "../app/types";
import {
  EvalHeader,
  LogFile,
  LogFiles,
  LogOverview,
} from "../client/api/types";
import { createLogger } from "../utils/logger";
import { StoreState } from "./store";

const log = createLogger("Log Slice");

const kEmptyLogs: LogFiles = {
  log_dir: "",
  files: [],
};

export interface LogsSlice {
  logs: LogsState;
  logsActions: {
    // Update State
    setLogs: (logs: LogFiles) => void;
    setLogOverviews: (overviews: Record<string, LogOverview>) => void;
    loadLogOverviews: (logs: LogFile[]) => Promise<LogOverview[]>;
    updateLogOverviews: (overviews: Record<string, LogOverview>) => void;
    setLogOverviewsLoading: (loading: boolean) => void;
    setSelectedLogIndex: (index: number) => void;
    setSelectedLogFile: (logUrl: string) => void;

    // Fetch or update logs
    refreshLogs: () => Promise<void>;
    selectLogFile: (logUrl: string) => Promise<void>;
    loadLogs: () => Promise<LogFiles>;

    // Cross-file sample operations
    getAllCachedSamples: () => Promise<any[]>;
    queryCachedSamples: (filter?: {
      completed?: boolean;
      hasError?: boolean;
      scoreRange?: { min: number; max: number; scoreName?: string };
    }) => Promise<any[]>;

    // Try to fetch an eval-set
    loadEvalSetInfo: (logPath?: string) => Promise<EvalSet | undefined>;
    setEvalSetInfo: (info: EvalSet | undefined) => void;
    clearEvalSetInfo: () => void;

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
  logs: kEmptyLogs,
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
      setLogs: (logs: LogFiles) => {
        set((state) => {
          state.logs.logs = logs;
          state.logs.selectedLogFile =
            state.logs.selectedLogIndex > -1
              ? logs.files[state.logs.selectedLogIndex]?.name
              : undefined;
        });
      },
      setLogOverviews: (overviews: Record<string, LogOverview>) =>
        set((state) => {
          state.logs.logOverviews = overviews;
        }),
      loadLogOverviews: async (logs: LogFile[]) => {
        const state = get();
        const api = state.api;
        if (!api) {
          console.error("API not initialized in LogsStore");
          return [];
        }

        const filePaths = logs.map((log) => log.name);

        // OPTIONAL: Try cache first (non-blocking, fail silently)
        let cached: Record<string, LogOverview> = {};
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
          const headers = await api.get_log_overviews(
            filesToLoad.map((log) => log.name),
          );

          // Process results and update store
          const headerMap: Record<string, LogOverview> = {};
          for (let i = 0; i < filesToLoad.length; i++) {
            const logFile = filesToLoad[i];
            const header = headers[i];
            if (header) {
              headerMap[logFile.name] = header as LogOverview;
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

          // OPTIONAL: Cache new results (completely non-blocking)
          setTimeout(() => {
            const dbService = get().databaseService;
            if (dbService && Object.keys(headerMap).length > 0) {
              dbService.cacheLogSummaries(headerMap).catch(() => {
                // Silently ignore cache errors
              });
            }
          }, 0);

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
          const file = state.logs.logs.files[selectedLogIndex];
          state.logs.selectedLogFile = file ? file.name : undefined;
        });
      },
      updateLogOverviews: (overviews: Record<string, LogOverview>) =>
        set((state) => {
          state.logs.logOverviews = {
            ...get().logs.logOverviews,
            ...overviews,
          };
        }),

      setSelectedLogFile: (logUrl: string) => {
        const state = get();
        const index = state.logs.logs.files.findIndex((val: { name: string }) =>
          logUrl.endsWith(val.name),
        );

        if (index > -1) {
          state.logsActions.setSelectedLogIndex(index);
          state.logs.selectedLogFile =
            state.logs.logs.files[index]?.name ?? undefined;
        }
      },

      // Helper function to load logs
      loadLogs: async () => {
        const api = get().api;
        if (!api) {
          console.error("API not initialized in LogsStore");
          return kEmptyLogs;
        }

        // Get log files from API to initialize database with log_dir
        let logFiles: LogFiles;
        try {
          log.debug("LOADING LOG FILES FROM API");
          logFiles = await api.get_log_paths();

          // Initialize database with log directory
          const databaseService = get().databaseService;
          if (databaseService && logFiles.log_dir) {
            try {
              await databaseService.openDatabase(logFiles.log_dir);
            } catch (e) {
              // Silently ignore database initialization errors
            }
          }
        } catch (e) {
          console.log(e);
          get().appActions.setStatus({ loading: false, error: e as Error });
          return kEmptyLogs;
        }

        // OPTIONAL: Try cache after DB is initialized (non-blocking, fail silently)
        const dbService = get().databaseService;
        if (dbService) {
          try {
            const cached = await dbService.getCachedLogFiles();
            if (cached) {
              log.debug("LOADED LOG FILES FROM CACHE");

              // Still cache the fresh data in background (non-blocking)
              setTimeout(() => {
                const dbSvc = get().databaseService;
                if (dbSvc) {
                  dbSvc.cacheLogFiles(logFiles).catch(() => {
                    // Silently ignore cache errors
                  });
                }
              }, 0);

              return cached;
            }
          } catch (e) {
            // Cache read failed, use API results we already have
          }
        }

        // Cache the result we got from API (completely non-blocking)
        setTimeout(() => {
          const dbService = get().databaseService;
          if (dbService) {
            dbService.cacheLogFiles(logFiles).catch(() => {
              // Silently ignore cache errors
            });
          }
        }, 0);

        return logFiles;
      },
      refreshLogs: async () => {
        log.debug("REFRESH LOGS");
        const state = get();
        // Preserve the selected log even if new logs appear
        const currentLog =
          state.logs.selectedLogIndex > -1
            ? state.logs.logs.files[state.logs.selectedLogIndex]
            : undefined;

        // Set the logs first
        const refreshedLogs = await state.logsActions.loadLogs();
        state.logsActions.setLogs(refreshedLogs || kEmptyLogs);

        if (currentLog) {
          const newIndex = refreshedLogs?.files.findIndex((file) =>
            currentLog.name.endsWith(file.name),
          );

          if (newIndex !== undefined && newIndex !== -1) {
            state.logsActions.setSelectedLogIndex(newIndex);
          }
        }
      },
      loadEvalSetInfo: async (logPath?: string) => {
        const api = get().api;
        if (!api) {
          console.error("API not initialized in LogsStore");
          return undefined;
        }

        const info = await api.get_eval_set_info(logPath);
        return info;
      },
      setEvalSetInfo: (info: EvalSet | undefined) => {
        set((state) => {
          state.logs.evalSet = info;
        });
      },
      clearEvalSetInfo: () => {
        set((state) => {
          state.logs.evalSet = undefined;
        });
      },
      // Select a specific log file
      selectLogFile: async (logUrl: string) => {
        const state = get();
        const index = state.logs.logs.files.findIndex((val: { name: string }) =>
          val.name.endsWith(logUrl),
        );

        // It is already loaded
        if (index > -1) {
          state.logsActions.setSelectedLogIndex(index);
        } else {
          // It isn't yet loaded, so refresh the logs and try to load it from there
          const result = await state.logsActions.loadLogs();
          const idx = result?.files.findIndex((file) =>
            file.name.endsWith(logUrl),
          );

          state.logsActions.setLogs(result || kEmptyLogs);
          state.logsActions.setSelectedLogIndex(
            idx !== undefined && idx > -1 ? idx : 0,
          );
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
