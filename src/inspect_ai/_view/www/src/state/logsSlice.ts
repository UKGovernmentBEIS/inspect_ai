import {
  ColumnFiltersState,
  ColumnResizeMode,
  SortingState,
} from "@tanstack/react-table";
import { GridState } from "ag-grid-community";
import { EvalSet } from "../@types/log";
import { DisplayedSample, LogsState } from "../app/types";
import {
  EvalHeader,
  LogDetails,
  LogHandle,
  LogPreview,
} from "../client/api/types";
import { DatabaseService } from "../client/database";
import { createLogger } from "../utils/logger";
import { isUri, join } from "../utils/uri";
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

    updateLogDetails: (details: Record<string, LogDetails>) => void;

    // Fetch or update logs
    initLogDir: () => Promise<string | undefined>;
    ensureReplication: () => Promise<void>;
    syncLogs: () => Promise<LogHandle[]>;

    setSelectedLogFile: (logFile: string) => void;
    clearSelectedLogFile: () => void;

    // Cross-file sample operations
    getAllCachedSamples: () => Promise<any[]>;
    queryCachedSamples: (filter?: {
      completed?: boolean;
      hasError?: boolean;
      scoreRange?: { min: number; max: number; scoreName?: string };
    }) => Promise<any[]>;

    // Try to fetch an eval-set
    syncEvalSetInfo: (logPath?: string) => Promise<EvalSet | undefined>;

    updateFlowData: (flowPath: string, flowData?: string) => void;

    setSorting: (sorting: SortingState) => void;
    setFiltering: (filtering: ColumnFiltersState) => void;
    setGlobalFilter: (globalFilter: string) => void;
    setColumnResizeMode: (mode: ColumnResizeMode) => void;
    setColumnSize: (columnId: string, size: number) => void;
    setFilteredCount: (count: number) => void;
    setWatchedLogs: (logs: LogHandle[]) => void;
    clearWatchedLogs: () => void;
    setSelectedRowIndex: (index: number | null) => void;

    setGridState: (gridState: GridState) => void;
    clearGridState: () => void;
    setDisplayedSamples: (samples: Array<DisplayedSample>) => void;
    clearDisplayedSamples: () => void;
    setColumnVisibility: (visibility: Record<string, boolean>) => void;
    setPreviousSamplesPath: (path: string | undefined) => void;
  };
}

const initialState: LogsState = {
  logDir: undefined,
  logs: [],
  logPreviews: {},
  logDetails: {},
  selectedLogFile: undefined as string | undefined,
  listing: {},
  pendingRequests: new Map<string, Promise<EvalHeader | null>>(),
  dbStats: {
    logCount: 0,
    previewCount: 0,
    detailsCount: 0,
  },
  samplesListState: {
    columnVisibility: {},
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
      setLogDir: (logDir?: string) => {
        set((state) => {
          if (logDir !== state.logs.logDir) {
            state.logs.logDir = logDir;
            state.logs.samplesListState.gridState = undefined;
          }
        });
      },
      setLogHandles: (logs: LogHandle[]) =>
        set((state) => {
          state.logs.logs = logs;
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

      updateLogDetails: (details: Record<string, LogDetails>) =>
        set((state) => {
          state.logs.logDetails = {
            ...get().logs.logDetails,
            ...details,
          };
        }),
      setGridState: (gridState: GridState | undefined) => {
        set((state) => {
          state.logs.samplesListState.gridState = gridState;
        });
      },
      clearGridState: () => {
        set((state) => {
          state.logs.samplesListState.gridState = undefined;
        });
      },
      setDisplayedSamples: (samples: Array<DisplayedSample>) => {
        const currentDisplaySamples =
          get().logs.samplesListState.displayedSamples;
        set((state) => {
          if (!displaySamplesEqual(currentDisplaySamples, samples)) {
            state.logs.samplesListState.displayedSamples = samples;
          }
        });
      },
      clearDisplayedSamples: () => {
        set((state) => {
          state.logs.samplesListState.displayedSamples = undefined;
        });
      },
      setColumnVisibility: (visibility: Record<string, boolean>) => {
        set((state) => {
          state.logs.samplesListState.columnVisibility = visibility;
        });
      },
      setPreviousSamplesPath: (path: string | undefined) => {
        set((state) => {
          state.logs.samplesListState.previousSamplesPath = path;
        });
      },
      initLogDir: async () => {
        const api = get().api;
        if (!api) {
          console.error("API not initialized in LogsStore");
          return undefined;
        }

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
        if (get().logs.logDir !== logDir) {
          get().logsActions.setLogDir(logDir);
        }
        return logDir;
      },
      ensureReplication: async () => {
        const state = get();
        if (state.logs.logDir) {
          await state.logsActions.syncLogs();
        }
      },
      syncLogs: async () => {
        const api = get().api;
        if (!api) {
          console.error("API not initialized in LogsStore");
          return [];
        }

        const databaseService = get().databaseService;
        const useProgress = !!databaseService?.getLogDir();
        if (useProgress) {
          get().appActions.setLoading(true);
        }

        // Determine the log directory
        const logDir = await get().logsActions.initLogDir();

        // Setup up the database service
        const initDatabase =
          !databaseService || databaseService.getLogDir() !== logDir;

        if (initDatabase) {
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
              if (useProgress) {
                get().appActions.setLoading(false, e as Error);
              }
              return;
            }
          };

          // Don't enable syncing if there is no log directory
          if (!logDir || get().app.singleFileMode) {
            if (useProgress) {
              get().appActions.setLoading(false);
            }
            return [];
          }

          // Activate the database for this log directory
          const databaseService = await initializeDatabase(logDir);
          if (!databaseService) {
            // No database service available
            throw new Error("Database service not available");
          }

          // Activate replication for this database
          await get().replicationService?.startReplication(
            databaseService,
            api,
            {
              setLogHandles: (logs: LogHandle[]) => {
                const state = get();
                state.logsActions.setLogHandles(logs);
              },
              getSelectedLog: () => {
                const state = get();
                if (!state.logs.selectedLogFile) {
                  return undefined;
                }
                return state.logs.logs.find((handle) => {
                  return handle.name.endsWith(state.logs.selectedLogFile!);
                });
              },
              setSelectedLogFile: (logFile: string) => {
                const state = get();
                state.logsActions.setSelectedLogFile(logFile);
              },
              updateLogPreviews: (previews: Record<string, LogPreview>) => {
                const state = get();
                state.logsActions.updateLogPreviews(previews);
              },
              updateLogDetails: (details: Record<string, LogDetails>) => {
                const state = get();
                state.logsActions.updateLogDetails(details);
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
            },
          );
        }

        if (useProgress) {
          get().appActions.setLoading(false);
        }

        // Sync
        return (await get().replicationService?.sync(initDatabase)) || [];
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
      updateFlowData: (flowPath: string, flowData?: string) => {
        set((state) => {
          state.logs.flowDir = flowPath;
          state.logs.flow = flowData;
        });
      },
      // Select a specific log file
      setSelectedLogFile: async (logFile: string) => {
        const state = get();
        const isInFileList =
          state.logs.logs.findIndex((val: { name: string }) =>
            val.name.endsWith(logFile),
          ) !== -1;

        if (!isInFileList) {
          if (
            state.replicationService?.isReplicating() &&
            !state.app.singleFileMode
          ) {
            await state.logsActions.syncLogs();
            const logHandle = state.logs.logs.find((val: { name: string }) =>
              val.name.endsWith(logFile),
            );
            if (!logHandle) {
              throw new Error(`Log file not found: ${logFile}`);
            }
          } else {
            state.logsActions.setLogHandles([{ name: logFile }]);
          }
        }
        set((state) => {
          const absoluteLogfile = isUri(logFile)
            ? logFile
            : join(logFile, state.logs.logDir);
          state.logs.selectedLogFile = absoluteLogfile;
        });
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
      clearSelectedLogFile: () => {
        set((state) => {
          state.logs.selectedLogFile = undefined;
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

const displaySamplesEqual = (
  a: DisplayedSample[] | undefined,
  b: DisplayedSample[] | undefined,
): boolean => {
  if (!a && !b) return true;
  if (!a || !b) return false;
  if (a.length !== b.length) return false;

  for (let i = 0; i < a.length; i++) {
    if (
      a[i].logFile !== b[i].logFile ||
      a[i].sampleId !== b[i].sampleId ||
      a[i].epoch !== b[i].epoch
    ) {
      return false;
    }
  }
  return true;
};
