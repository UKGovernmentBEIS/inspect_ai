import { FilterError, LogState, ScoreLabel } from "../app/types";
import { LogInfo, PendingSamples } from "../client/api/types";
import { toBasicInfo } from "../client/utils/type-utils";
import { kDefaultSort, kLogViewInfoTabId } from "../constants";
import { createLogger } from "../utils/logger";
import { createLogPolling } from "./logPolling";
import { StoreState } from "./store";

const log = createLogger("logSlice");

export interface LogSlice {
  log: LogState;
  logActions: {
    selectSample: (index: number) => void;

    // Set the selected log summary
    setSelectedLogSummary: (summary: LogInfo) => void;

    // Clear the selected log summary
    clearSelectedLogSummary: () => void;

    // Update pending sample information
    setPendingSampleSummaries: (samples: PendingSamples) => void;

    // Set filter criteria
    setFilter: (filter: string) => void;

    // Set the filter error
    setFilterError: (error: FilterError) => void;

    // Clear the filter error
    clearFilterError: () => void;

    // Set epoch filter
    setEpoch: (epoch: string) => void;

    // Set sort order and update groupBy
    setSort: (sort: string) => void;

    // Set score labels
    setSelectedScores: (scores: ScoreLabel[]) => void;

    // Set available scores
    setScores: (scores: ScoreLabel[]) => void;

    // Reset filter state to defaults
    resetFiltering: () => void;

    // Load log
    syncLog: (logFileName: string) => Promise<void>;

    // Refresh the current log
    refreshLog: () => Promise<void>;

    // Poll the currently selected log
    pollLog: () => Promise<void>;

    // Clear the currently loaded log
    clearLog: () => void;
  };
}

// Initial state
const initialState = {
  // Log state
  selectedSampleIndex: -1,
  selectedLogSummary: undefined,
  pendingSampleSummaries: undefined,
  loadedLog: undefined,

  // Filter state
  filter: "",
  filterError: undefined,

  epoch: "all",
  sort: kDefaultSort,
  selectedScores: undefined,
  scores: undefined,
};

// Create the app slice using StoreState directly
export const createLogSlice = (
  set: (fn: (state: StoreState) => void) => void,
  get: () => StoreState,
  _store: any,
): [LogSlice, () => void] => {
  const logPolling = createLogPolling(get, set);

  const slice = {
    // State
    log: initialState,

    // Actions
    logActions: {
      selectSample: (index: number) =>
        set((state) => {
          state.log.selectedSampleIndex = index;
        }),

      setSelectedLogSummary: (selectedLogSummary: LogInfo) => {
        set((state) => {
          state.log.selectedLogSummary = selectedLogSummary;
          state.log.selectedScores = undefined;
        });

        if (
          selectedLogSummary.status !== "started" &&
          selectedLogSummary.sampleSummaries.length === 0
        ) {
          // If there are no samples, use the workspace tab id by default
          get().appActions.setWorkspaceTab(kLogViewInfoTabId);
        }
      },

      clearSelectedLogSummary: () => {
        set((state) => {
          state.log.selectedLogSummary = undefined;
        });
      },
      setPendingSampleSummaries: (pendingSampleSummaries: PendingSamples) =>
        set((state) => {
          state.log.pendingSampleSummaries = pendingSampleSummaries;
        }),

      setFilter: (filter: string) =>
        set((state) => {
          state.log.filter = filter;
        }),
      setFilterError: (error: FilterError) =>
        set((state) => {
          state.log.filterError = error;
        }),
      clearFilterError: () => {
        set((state) => {
          state.log.filterError = undefined;
        });
      },
      setEpoch: (epoch: string) =>
        set((state) => {
          state.log.epoch = epoch;
        }),
      setSort: (sort: string) =>
        set((state) => {
          state.log.sort = sort;
        }),
      setSelectedScores: (scores: ScoreLabel[]) =>
        set((state) => {
          state.log.selectedScores = scores;
        }),
      setScores: (scores: ScoreLabel[]) =>
        set((state) => {
          state.log.scores = scores;
        }),
      resetFiltering: () =>
        set((state) => {
          state.log.filter = "";
          state.log.filterError = undefined;
          state.log.epoch = "all";
          state.log.sort = kDefaultSort;
          state.log.selectedScores = state.log.scores?.slice(0, 1);
        }),

      syncLog: async (logFileName: string) => {
        const state = get();
        const api = state.api;

        if (!api) {
          console.error("API not initialized in Store");
          return;
        }

        log.debug(`Load log: ${logFileName}`);

        // OPTIONAL: Try cache first (non-blocking, fail silently)
        const dbService = state.databaseService;
        if (dbService && dbService.opened()) {
          try {
            const cachedInfo = await dbService.getCachedLogInfo(logFileName);
            if (cachedInfo) {
              log.debug(`Using cached log info for: ${logFileName}`);
              state.logActions.setSelectedLogSummary(cachedInfo);
              // Still fetch fresh data in background to update cache
              api.get_log_info(logFileName).then((freshInfo) => {
                state.logActions.setSelectedLogSummary(freshInfo);
                dbService.cacheLogInfo(logFileName, freshInfo).catch(() => {
                  // Silently ignore cache errors
                });
              });
              // Continue with rest of the function using cached data
              const header = {
                [logFileName]: toBasicInfo(cachedInfo),
              };
              state.logsActions.updateLogOverviews(header);
              set((state) => {
                state.log.loadedLog = logFileName;
              });
              return;
            }
          } catch (e) {
            // Cache read failed, continue with normal flow
          }
        }

        try {
          const logContents = await api.get_log_info(logFileName);
          state.logActions.setSelectedLogSummary(logContents);

          // OPTIONAL: Cache log info (completely non-blocking)
          if (dbService) {
            setTimeout(() => {
              dbService.cacheLogInfo(logFileName, logContents).catch(() => {
                // Silently ignore cache errors
              });
            }, 0);
          }

          // Push the updated header information up
          const header = {
            [logFileName]: toBasicInfo(logContents),
          };

          state.logsActions.updateLogOverviews(header);
          set((state) => {
            state.log.loadedLog = logFileName;
          });

          // Start polling for pending samples
          logPolling.startPolling(logFileName);
        } catch (error) {
          log.error("Error loading log:", error);
          throw error;
        }
      },

      clearLog: () => {
        set((state) => {
          state.log.loadedLog = undefined;
        });
      },

      pollLog: async () => {
        const currentLog = get().log.loadedLog;
        if (currentLog) {
          logPolling.startPolling(currentLog);
        }
      },

      refreshLog: async () => {
        const state = get();
        const api = state.api;
        const selectedLogFile = state.logs.selectedLogFile;

        if (!api || !selectedLogFile) {
          return;
        }

        log.debug(`refresh: ${selectedLogFile}`);
        try {
          const logContents = await api.get_log_info(selectedLogFile);
          state.logActions.setSelectedLogSummary(logContents);
        } catch (error) {
          log.error("Error refreshing log:", error);
          throw error;
        }
      },
    },
  } as const;

  const cleanup = () => {
    logPolling.cleanup();
  };

  return [slice, cleanup];
};

// Initialize app slice with StoreState
export const initalializeLogSlice = (
  set: (fn: (state: StoreState) => void) => void,
) => {
  set((state) => {
    if (!state.log) {
      state.log = initialState;
    }
  });
};
