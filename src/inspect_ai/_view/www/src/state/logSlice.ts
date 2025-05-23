import { FilterError, LogState, ScoreLabel } from "../app/types";
import { EvalSummary, PendingSamples } from "../client/api/types";
import { kDefaultSort, kLogViewInfoTabId } from "../constants";
import { createLogger } from "../utils/logger";
import { createLogPolling } from "./logPolling";
import { ScorerInfo } from "./scoring";
import { StoreState } from "./store";

const log = createLogger("logSlice");

export interface LogSlice {
  log: LogState;
  logActions: {
    selectSample: (index: number) => void;

    // Set the selected log summary
    setSelectedLogSummary: (summary: EvalSummary) => void;

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

    // Set score label
    setScore: (score: ScoreLabel) => void;

    // Set available scores
    setScores: (scores: ScorerInfo[]) => void;

    // Reset filter state to defaults
    resetFiltering: () => void;

    // Load log
    loadLog: (logFileName: string) => Promise<void>;

    // Refresh the current log
    refreshLog: () => Promise<void>;

    // Poll the currently selected log
    pollLog: () => Promise<void>;
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
  score: undefined,
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

      setSelectedLogSummary: (selectedLogSummary: EvalSummary) => {
        set((state) => {
          state.log.selectedLogSummary = selectedLogSummary;
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
      setScore: (score: ScoreLabel) =>
        set((state) => {
          state.log.score = score;
        }),
      setScores: (scores: ScorerInfo[]) =>
        set((state) => {
          state.log.scores = scores;
        }),
      resetFiltering: () =>
        set((state) => {
          state.log.filter = "";
          state.log.filterError = undefined;
          state.log.epoch = "all";
          state.log.sort = kDefaultSort;
          state.log.score = undefined;
        }),

      loadLog: async (logFileName: string) => {
        const state = get();
        const api = state.api;

        if (!api) {
          console.error("API not initialized in Store");
          return;
        }

        log.debug(`Load log: ${logFileName}`);
        try {
          const logContents = await api.get_log_summary(logFileName);
          state.logActions.setSelectedLogSummary(logContents);

          // Push the updated header information up
          const header = {
            [logFileName]: {
              version: logContents.version,
              status: logContents.status,
              eval: logContents.eval,
              plan: logContents.plan,
              results:
                logContents.results !== null ? logContents.results : undefined,
              stats: logContents.stats,
              error: logContents.error !== null ? logContents.error : undefined,
            },
          };

          state.logsActions.updateLogHeaders(header);
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
          const logContents = await api.get_log_summary(selectedLogFile);
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
