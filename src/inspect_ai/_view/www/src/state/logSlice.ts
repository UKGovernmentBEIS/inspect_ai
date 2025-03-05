import { EvalSummary, PendingSamples } from "../api/types";
import { kDefaultSort } from "../constants";
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
  };
}

// Initial state
const initialState = {
  // Log state
  selectedSampleIndex: -1,
  selectedLogSummary: undefined,
  pendingSampleSummaries: undefined,
  api: null,

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
) => {
  const logPolling = createLogPolling(get, set);

  return {
    // State
    log: initialState,

    // Actions
    logActions: {
      selectSample: (index: number) =>
        set((state) => {
          state.log.selectedSampleIndex = index;
        }),

      setSelectedLogSummary: (selectedLogSummary: EvalSummary) =>
        set((state) => {
          state.log.selectedLogSummary = selectedLogSummary;
        }),

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

        log.debug(`LOAD LOG: ${logFileName}`);
        try {
          const logContents = await api.get_log_summary(logFileName);
          state.logActions.setSelectedLogSummary(logContents);
          state.logActions.resetFiltering();

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

          // Start polling for pending samples
          logPolling.startPolling(logFileName);
        } catch (error) {
          log.error("Error loading log:", error);
        }
      },

      refreshLog: async () => {
        const state = get();
        const api = state.api;
        const selectedLogFile = state.logsActions.getSelectedLogFile();

        if (!api || !selectedLogFile) {
          return;
        }

        log.debug(`REFRESH: ${selectedLogFile}`);
        try {
          const logContents = await api.get_log_summary(selectedLogFile);
          state.logActions.setSelectedLogSummary(logContents);
        } catch (error) {
          log.error("Error refreshing log:", error);
        }
      },
    },
  } as const;
};

// Initialize app slice with StoreState
export const initalializeLogSlice = (
  set: (fn: (state: StoreState) => void) => void,
  restoreState?: Partial<LogState>,
) => {
  set((state) => {
    state.log = { ...initialState };
    if (restoreState) {
      if (restoreState.epoch) {
        state.log.epoch = restoreState.epoch;
      }

      if (restoreState.filter) {
        state.log.filter = restoreState.filter;
      }

      if (restoreState.score) {
        state.log.score = restoreState.score;
      }

      if (restoreState.selectedSampleIndex) {
        state.log.selectedSampleIndex = restoreState.selectedSampleIndex;
      }

      if (restoreState.scores) {
        state.log.scores = restoreState.scores;
      }
      if (restoreState.selectedLogSummary) {
        state.log.selectedLogSummary = restoreState.selectedLogSummary;
      }
    }
  });
};
