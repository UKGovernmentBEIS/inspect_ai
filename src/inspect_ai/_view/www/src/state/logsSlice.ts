import {
  ColumnFiltersState,
  ColumnResizeMode,
  SortingState,
} from "@tanstack/react-table";
import { LogsState } from "../app/types";
import {
  EvalLogHeader,
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

    setSorting: (sorting: SortingState) => void;
    setFiltering: (filtering: ColumnFiltersState) => void;
    setGlobalFilter: (globalFilter: string) => void;
    setColumnResizeMode: (mode: ColumnResizeMode) => void;
    setColumnSize: (columnId: string, size: number) => void;
    setFilteredCount: (count: number) => void;
    setWatchedLogs: (logs: LogFile[]) => void;
    clearWatchedLogs: () => void;
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
  pendingRequests: new Map<string, Promise<EvalLogHeader | null>>(),
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

        // Filter out files that are already loaded or currently loading
        // reload headers with "started" status as they may have changed
        const filesToLoad = logs.filter((logFile) => {
          const existing = state.logs.logOverviews[logFile.name];
          const isLoading = state.logs.loadingFiles.has(logFile.name);

          // Always load if no existing header
          if (!existing) {
            return !isLoading;
          }

          // Reload if header status is "started" or "error" (but not if already loading)
          if (existing.status === "started" || existing.status === "error") {
            return !isLoading;
          }

          // Skip if already loaded with final status
          return false;
        });

        if (filesToLoad.length === 0) {
          return [];
        }

        // Mark files as loading
        set((state) => {
          filesToLoad.forEach((logFile) => {
            state.logs.loadingFiles.add(logFile.name);
          });
        });

        // Set global loading state if this is the first batch
        const wasLoading = get().logs.logOverviewsLoading;
        if (!wasLoading) {
          set((state) => {
            state.logs.logOverviewsLoading = true;
          });
        }

        try {
          log.debug(`LOADING LOG OVERVIEWS for ${filesToLoad.length} files`);
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
            if (state.logs.loadingFiles.size === 0) {
              state.logs.logOverviewsLoading = false;
            }
          });

          return headers;
        } catch (error) {
          log.error("Error loading log headers", error);

          // Clear loading state on error
          set((state) => {
            filesToLoad.forEach((logFile) => {
              state.logs.loadingFiles.delete(logFile.name);
            });
            if (state.logs.loadingFiles.size === 0) {
              state.logs.logOverviewsLoading = false;
            }
          });

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

        try {
          log.debug("LOADING LOG FILES");
          return await api.get_log_paths();
        } catch (e) {
          console.log(e);
          get().appActions.setStatus({ loading: false, error: e as Error });
          return kEmptyLogs;
        }
      },
      refreshLogs: async () => {
        log.debug("REFRESH LOGS");
        const state = get();
        const refreshedLogs = await state.logsActions.loadLogs();

        // Preserve the selected log even if new logs appear
        const currentLog =
          state.logs.logs.files[
            state.logs.selectedLogIndex > -1 ? state.logs.selectedLogIndex : 0
          ];

        // Set the logs first
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
    },
  } as const;

  const cleanup = () => {};

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
