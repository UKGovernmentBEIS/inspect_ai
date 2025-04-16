import { EvalSummary, PendingSamples } from "../api/types";
import { kDefaultSort, kInfoWorkspaceTabId } from "../constants";
import { ScorerInfo } from "../scoring/utils";
import { LogState, ScoreFilter, ScoreLabel } from "../types";
import { createLogger } from "../utils/logger";
import { createLogPolling } from "./logPolling";
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
    setFilter: (filter: ScoreFilter) => void;

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
  filter: {},
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
          get().appActions.setWorkspaceTab(kInfoWorkspaceTabId);
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

      setFilter: (filter: ScoreFilter) =>
        set((state) => {
          state.log.filter = filter;
        }),
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
          state.log.filter = {};
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
          state.logActions.setEpoch;

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
          }),
            // Start polling for pending samples
            logPolling.startPolling(logFileName);
        } catch (error) {
          log.error("Error loading log:", error);
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
        const selectedLogFile = state.logsActions.getSelectedLogFile();

        if (!api || !selectedLogFile) {
          return;
        }

        log.debug(`refresh: ${selectedLogFile}`);
        try {
          const logContents = await api.get_log_summary(selectedLogFile);
          state.logActions.setSelectedLogSummary(logContents);
        } catch (error) {
          log.error("Error refreshing log:", error);
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
