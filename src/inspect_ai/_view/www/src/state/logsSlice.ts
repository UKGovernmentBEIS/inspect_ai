import {
  ColumnFiltersState,
  ColumnResizeMode,
  SortingState,
} from "@tanstack/react-table";
import { EvalSet } from "../@types/log";
import { LogsState } from "../app/types";
import { EvalHeader, LogHandle, LogPreview } from "../client/api/types";
import { DatabaseService } from "../client/database";
import { createLogger } from "../utils/logger";
import { StoreState } from "./store";

const log = createLogger("Log Slice");

export interface LogsSlice {
  logs: LogsState;
  logsActions: {
    // Update State
    setLogDir: (logDir?: string) => void;
    setLogHandles: (logHandles: LogHandle[]) => void;

    updateLogPreviews: (previews: Record<string, LogPreview>) => void;

    syncLogPreviews: (logs: LogHandle[]) => Promise<void>;

    setSelectedLogIndex: (index: number) => void;

    // Fetch or update logs
    syncLogs: () => Promise<LogHandle[]>;
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
    setWatchedLogs: (logs: LogHandle[]) => void;
    clearWatchedLogs: () => void;
    setSelectedRowIndex: (index: number | null) => void;
  };
}

const initialState: LogsState = {
  logDir: undefined,
  logs: [],
  logPreviews: {},
  selectedLogIndex: -1,
  selectedLogFile: undefined as string | undefined,
  listing: {},
  pendingRequests: new Map<string, Promise<EvalHeader | null>>(),
  dbStats: {
    logCount: 0,
    previewCount: 0,
    detailsCount: 0,
  },
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
      setLogHandles: (logs: LogHandle[]) =>
        set((state) => {
          state.logs.logs = logs;
          state.logs.selectedLogFile =
            state.logs.selectedLogIndex > -1
              ? logs[state.logs.selectedLogIndex]?.name
              : undefined;
        }),
      syncLogPreviews: async (logs: LogHandle[]) => {
        const state = get();
        const api = state.api;
        if (!api) {
          console.error("API not initialized in LogsStore");
          return;
        }

        if (!state.replicationService) {
          console.error("Replication service not initialized in LogsStore");
          return;
        }
        try {
          await state.replicationService?.loadLogPreviews({ logs });
        } catch (e) {
          console.error("Failed to sync log previews", e);
        }
      },
      updateLogPreviews: (previews: Record<string, LogPreview>) =>
        set((state) => {
          state.logs.logPreviews = {
            ...get().logs.logPreviews,
            ...previews,
          };
        }),

      setSelectedLogIndex: (selectedLogIndex: number) => {
        set((state) => {
          state.logs.selectedLogIndex = selectedLogIndex;
          const file = state.logs.logs[selectedLogIndex];
          state.logs.selectedLogFile = file ? file.name : undefined;
        });
      },
      syncLogs: async () => {
        const api = get().api;
        if (!api) {
          console.error("API not initialized in LogsStore");
          return [];
        }

        get().appActions.setLoading(true);

        // Determine the log directory
        const loadLogDir = async () => {
          try {
            return await api.get_log_dir();
          } catch (e) {
            console.log(e);
            get().appActions.setLoading(false, e as Error);
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
            get().appActions.setLoading(false, e as Error);
            return;
          }
        };

        // Activate the database for this log directory
        const databaseService = await initializeDatabase(logDir);
        if (!databaseService) {
          // No database service available
          throw new Error("Database service not available");
        }

        // Activate replication for this database
        get().replicationService?.startReplication(databaseService, api, {
          setLogHandles: (logs: LogHandle[]) => {
            const state = get();
            state.logsActions.setLogHandles(logs);
          },
          getSelectedLog: () => {
            const state = get();
            return state.logs.selectedLogIndex > -1
              ? state.logs.logs[state.logs.selectedLogIndex]
              : undefined;
          },
          setSelectedLogIndex: (index: number) => {
            const state = get();
            state.logsActions.setSelectedLogIndex(index);
          },
          updateLogPreviews: (previews: Record<string, LogPreview>) => {
            const state = get();
            state.logsActions.updateLogPreviews(previews);
          },
          setLoading(loading: boolean) {
            const state = get();
            state.appActions.setLoading(loading);
          },
          setBackgroundSyncing(syncing: boolean) {
            set((state) => {
              state.app.status.syncing = syncing;
            });
          },
          setDbStats(stats: {
            logCount: number;
            previewCount: number;
            detailsCount: number;
          }) {
            set((state) => {
              state.logs.dbStats = stats;
            });
          },
        });

        get().appActions.setLoading(false);

        // Sync
        return (await get().replicationService?.sync(true)) || [];
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
        const index = state.logs.logs.findIndex((val: { name: string }) =>
          val.name.endsWith(logUrl),
        );

        // It is already loaded
        if (index > -1) {
          state.logsActions.setSelectedLogIndex(index);
        } else {
          // It isn't yet loaded, so refresh the logs and try to load it from there
          const logHandles = await state.logsActions.syncLogs();

          const idx = logHandles.findIndex((file) =>
            file.name.endsWith(logUrl),
          );

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
      setWatchedLogs: (logs: LogHandle[]) => {
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
          const samples = await dbService.readAllSampleSummaries();
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
