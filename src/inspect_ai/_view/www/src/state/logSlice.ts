import { sampleHandlesEqual } from "../app/shared/sample";
import { FilterError, LogState, ScoreLabel } from "../app/types";
import { LogDetails, PendingSamples } from "../client/api/types";
import { toLogPreview } from "../client/utils/type-utils";
import { kLogViewInfoTabId } from "../constants";
import { createLogger } from "../utils/logger";
import { isUri, join } from "../utils/uri";
import { createLogPolling } from "./logPolling";
import { StoreState } from "./store";

const log = createLogger("logSlice");

export interface LogSlice {
  log: LogState;
  logActions: {
    selectSample: (
      sampleId: string | number,
      epoch: number,
      logFile: string,
    ) => void;
    clearSelectedSample: () => void;

    // Set the selected log summary
    setSelectedLogDetails: (details: LogDetails) => void;

    // Clear the selected log summary
    clearSelectedLogDetails: () => void;

    // Update pending sample information
    setPendingSampleSummaries: (samples: PendingSamples) => void;
    clearPendingSampleSummaries: () => void;

    // Set filter criteria
    setFilter: (filter: string) => void;

    // Set the filter error
    setFilterError: (error: FilterError) => void;

    // Clear the filter error
    clearFilterError: () => void;

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

    setFilteredSampleCount: (count: number) => void;
    clearFilteredSampleCount: () => void;
  };
}

// Initial state
const initialState = {
  // Log state
  selectedSampleId: undefined,
  selectedSampleEpoch: undefined,
  selectedLogDetails: undefined,
  pendingSampleSummaries: undefined,
  loadedLog: undefined,

  // Filter state
  filter: "",
  filterError: undefined,

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
      selectSample: (
        sampleId: string | number,
        epoch: number,
        logFile: string,
      ) => {
        // Ignore if already selected
        const currentSample = get().log.selectedSampleHandle;
        if (
          sampleHandlesEqual(currentSample, {
            id: sampleId,
            epoch,
            logFile,
          })
        ) {
          return;
        }

        set((state) => {
          state.log.selectedSampleHandle = { id: sampleId, epoch, logFile };
        });
      },
      clearSelectedSample: () => {
        set((state) => {
          state.log.selectedSampleHandle = undefined;
        });
      },
      setSelectedLogDetails: (details: LogDetails) => {
        set((state) => {
          state.log.selectedScores = undefined;
          state.log.selectedLogDetails = details;
        });

        if (
          details.status !== "started" &&
          details.sampleSummaries.length === 0
        ) {
          // If there are no samples, use the workspace tab id by default
          get().appActions.setWorkspaceTab(kLogViewInfoTabId);
        }
      },

      clearSelectedLogDetails: () => {
        set((state) => {
          state.log.selectedLogDetails = undefined;
        });
      },
      setPendingSampleSummaries: (pendingSampleSummaries: PendingSamples) => {
        set((state) => {
          state.log.pendingSampleSummaries = pendingSampleSummaries;
        });
      },
      clearPendingSampleSummaries: () => {
        set((state) => {
          state.log.pendingSampleSummaries = undefined;
        });
      },
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
          state.log.selectedScores = state.log.scores?.slice(0, 1);
        }),

      syncLog: async (logFileName: string) => {
        const state = get();
        const api = state.api;

        // Ensure there is a log dir
        let logDir = state.logs.logDir;
        if (state.logs.logDir === undefined) {
          logDir = await state.logsActions.initLogDir();
        }

        const logAbsPath = !isUri(logFileName)
          ? join(logFileName, logDir)
          : logFileName;

        if (!api) {
          console.error("API not initialized in Store");
          return;
        }

        log.debug(`Load log: ${logAbsPath}`);

        // Try reading the data in the database first
        const dbService = state.databaseService;
        if (dbService && dbService.opened()) {
          try {
            const cachedInfo =
              await dbService.readLogDetailsForFile(logAbsPath);
            if (cachedInfo) {
              log.debug(`Using cached log info for: ${logAbsPath}`);
              state.logActions.setSelectedLogDetails(cachedInfo);
              // Still fetch fresh data in background to update cache
              api.get_log_details(logAbsPath).then((logDetails) => {
                state.logActions.setSelectedLogDetails(logDetails);
                dbService.writeLogDetail(logAbsPath, logDetails).catch(() => {
                  // Silently ignore cache errors
                });
              });
              // Continue with rest of the function using cached data
              const header = {
                [logFileName]: toLogPreview(cachedInfo),
              };
              state.logsActions.updateLogPreviews(header);
              set((state) => {
                state.log.loadedLog = logFileName;
              });

              state.logActions.clearPendingSampleSummaries();
              logPolling.startPolling(logFileName);
              return;
            }
          } catch (e) {
            // Cache read failed, continue with normal flow
          }
        }

        try {
          const logDetails = await api.get_log_details(logFileName);
          state.logActions.setSelectedLogDetails(logDetails);

          // OPTIONAL: Cache log info (completely non-blocking)
          if (dbService) {
            setTimeout(() => {
              dbService.writeLogDetail(logFileName, logDetails).catch(() => {
                // Silently ignore cache errors
              });
            }, 0);
          }

          // Push the updated header information up
          const header = {
            [logFileName]: toLogPreview(logDetails),
          };

          state.logsActions.updateLogPreviews(header);
          set((state) => {
            state.log.loadedLog = logFileName;
          });

          // Start polling for pending samples
          state.logActions.clearPendingSampleSummaries();
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
          const logDetails = await api.get_log_details(selectedLogFile);
          state.logActions.setSelectedLogDetails(logDetails);
        } catch (error) {
          log.error("Error refreshing log:", error);
          throw error;
        }
      },
      setFilteredSampleCount: (count: number) => {
        set((state) => {
          state.log.filteredSampleCount = count;
        });
      },
      clearFilteredSampleCount: () => {
        set((state) => {
          state.log.filteredSampleCount = undefined;
        });
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
