import { useMemo } from "react";
import { create } from "zustand";
import { immer } from "zustand/middleware/immer";
import {
  ClientAPI,
  EvalSummary,
  PendingSamples,
  SampleSummary,
} from "../api/types";
import {
  kDefaultSort,
  kEpochAscVal,
  kSampleAscVal,
  kScoreAscVal,
} from "../constants";
import {
  createEvalDescriptor,
  createSamplesDescriptor,
} from "../samples/descriptor/samplesDescriptor";
import { filterSamples } from "../samples/sample-tools/filters";
import {
  byEpoch,
  bySample,
  sortSamples,
} from "../samples/sample-tools/SortFilter";
import {
  getAvailableScorers,
  getDefaultScorer,
  ScorerInfo,
} from "../scoring/utils";
import { LogState, ScoreFilter, ScoreLabel } from "../types";
import { createLogger } from "../utils/logger";
import { useLogsStore } from "./logsStore";

export interface LogStore extends LogState {
  // --- Core log state ---
  // The currently selected sample index
  selectedSampleIndex: number;

  // The currently selected log summary
  selectedLogSummary?: EvalSummary;

  // Running samples
  pendingSampleSummaries?: PendingSamples;

  // The api
  api: ClientAPI | null;

  // --- Filter-related state ---
  // The current filter criteria
  filter: ScoreFilter;

  // Selected epoch filter, 'all' means all epochs
  epoch: string;

  // Current sort order
  sort: string;

  // Currently selected score label
  score?: ScoreLabel;

  // Available scorers
  scores?: ScorerInfo[];

  // --- Actions ---
  // Select a sample using its index
  selectSample: (index: number) => void;

  // Set the selected log summary
  setSelectedLogSummary: (summary: EvalSummary) => void;

  // Update pending sample information
  setPendingSampleSummaries: (samples: PendingSamples) => void;

  /** Set filter criteria */
  setFilter: (filter: ScoreFilter) => void;

  /** Set epoch filter */
  setEpoch: (epoch: string) => void;

  /** Set sort order and update groupBy */
  setSort: (sort: string) => void;

  /** Set score label */
  setScore: (score: ScoreLabel) => void;

  /** Set available scores */
  setScores: (scores: ScorerInfo[]) => void;

  /** Reset filter state to defaults */
  resetFiltering: () => void;

  // --- API Functions ---
  // Initialize the store
  initializeStore: (api: ClientAPI, initialState?: Partial<LogState>) => void;

  // Load a specific log file
  loadLog: (logFileName: string) => Promise<void>;

  // Refresh the current log
  refreshLog: () => Promise<void>;

  // Get log state for persistence
  getState: () => { log: LogState };
}

// Combined initial state
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

// Create logger
const log = createLogger("logStore");

const useLogStore = create<LogStore>()(
  immer((set, get) => ({
    ...initialState,

    // ---- Log Actions ----
    selectSample: (index) => set({ selectedSampleIndex: index }),

    setSelectedLogSummary: (selectedLogSummary) => {
      set({ selectedLogSummary });
    },

    setPendingSampleSummaries: (pendingSampleSummaries) =>
      set({ pendingSampleSummaries }),

    // ---- Filter Actions ----
    setFilter: (filter) => set({ filter }),
    setEpoch: (epoch) => set({ epoch }),
    setSort: (sort) =>
      set((state) => {
        state.sort = sort;
      }),
    setScore: (score) => set({ score }),
    setScores: (scores) => set({ scores }),
    resetFiltering: () =>
      set({
        filter: {},
        epoch: "all",
        sort: kDefaultSort,
        score: undefined,
      }),

    // ---- API Functions ----
    initializeStore: (api, initialLogState) => {
      set((state) => {
        state.api = api;

        if (initialLogState) {
          Object.assign(state, initialLogState);
        }
      });
    },

    loadLog: async (logFileName) => {
      const state = get();
      const api = state.api;

      if (!api) {
        console.error("API not initialized in Store");
        return;
      }

      log.debug(`LOAD LOG: ${logFileName}`);
      try {
        const logContents = await api.get_log_summary(logFileName);
        set((state) => {
          state.selectedLogSummary = { ...logContents };
        });

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

        useLogsStore.getState().updateLogHeaders(header);

        // Start polling for pending samples
        startPollingPendingSamples(logFileName, get, set);
      } catch (error) {
        log.error("Error loading log:", error);
      }
    },

    refreshLog: async () => {
      const state = get();
      const api = state.api;
      const logsStore = useLogsStore.getState();
      const selectedLogFile = logsStore.getSelectedLogFile();

      if (!api || !selectedLogFile) {
        return;
      }

      log.debug(`REFRESH: ${selectedLogFile}`);
      try {
        const logContents = await api.get_log_summary(selectedLogFile);
        set((state) => {
          state.selectedLogSummary = logContents;
        });
      } catch (error) {
        log.error("Error refreshing log:", error);
      }
    },

    // For backward compatibility
    getState: () => ({ log: get() }),
  })),
);

// Function to merge log samples with pending samples
const mergeSampleSummaries = (
  logSamples: SampleSummary[],
  pendingSamples: SampleSummary[],
) => {
  // Create a map of existing sample IDs to avoid duplicates
  const existingSampleIds = new Set(
    logSamples.map((sample) => `${sample.id}-${sample.epoch}`),
  );

  // Filter out any pending samples that already exist in the log
  const uniquePendingSamples = pendingSamples
    .filter((sample) => !existingSampleIds.has(`${sample.id}-${sample.epoch}`))
    .map((sample) => {
      // Always mark pending items as incomplete to be sure we trigger polling
      return { ...sample, completed: false };
    });

  // Combine and return all samples
  return [...logSamples, ...uniquePendingSamples];
};

// Polling mechanism for pending samples
let currentPollCleanup: (() => void) | null = null;

const startPollingPendingSamples = (
  logFile: string,
  getState: () => LogStore,
  setState: (state: Partial<LogStore>) => void,
) => {
  // Clean up any existing polling
  if (currentPollCleanup) {
    currentPollCleanup();
    currentPollCleanup = null;
  }

  // Track whether polling is active
  const polling = {
    isActive: true,
    hadPending: false,
    currentEtag: getState().pendingSampleSummaries?.etag,
    currentRefresh: getState().pendingSampleSummaries?.refresh || 2,
    timeout: -1,
    retryCount: 0,
    maxRetries: 10,
  };

  // Define the poll function
  const poll = async () => {
    // Don't proceed if polling has been canceled or max retries reached
    if (!polling.isActive) {
      return;
    }

    const state = getState();
    const api = state.api;

    // Don't bother polling if the API doesn't support it
    if (!api?.get_log_pending_samples) return;

    try {
      log.debug(`POLL RUNNING SAMPLES: ${logFile}`);
      const pendingSamples = await api.get_log_pending_samples(
        logFile,
        polling.currentEtag,
      );

      // Check if we've been canceled during the API call
      if (!polling.isActive) {
        log.debug(`POLL RUNNING SAMPLES CANCELED: ${logFile}`);
        return;
      }

      if (pendingSamples.status === "OK" && pendingSamples.pendingSamples) {
        // Reset retry count on successful poll
        polling.retryCount = 0;

        // Update the closure variables with new values
        polling.currentEtag = pendingSamples.pendingSamples.etag;
        polling.currentRefresh =
          pendingSamples.pendingSamples.refresh || polling.currentRefresh;

        setState({
          pendingSampleSummaries: pendingSamples.pendingSamples,
        });

        getState().refreshLog();
        polling.hadPending = true;
      } else if (pendingSamples.status === "NotFound") {
        log.debug(`STOP POLLING RUNNING SAMPLES: ${logFile}`);
        if (polling.hadPending) {
          getState().refreshLog();
        }
        clearPendingSummaries(logFile, getState, setState);
        // stop polling
        polling.isActive = false;
        return;
      }

      // Schedule next poll if we haven't been canceled
      if (polling.isActive) {
        polling.timeout = setTimeout(poll, polling.currentRefresh * 1000);
      }
    } catch (error) {
      log.debug(`ERROR PENDING RUNNING SAMPLES: ${logFile}`);
      log.error("Error polling pending samples:", error);

      // Increment retry count
      polling.retryCount += 1;

      // Check if we've reached the maximum retries
      if (polling.retryCount >= polling.maxRetries) {
        log.error(
          `Giving up after ${polling.maxRetries} failed attempts to poll pending samples`,
        );
        polling.isActive = false;
        clearPendingSummaries(logFile, getState, setState);
        return;
      }

      // Schedule next poll with exponential backoff if we haven't been canceled
      if (polling.isActive) {
        // Calculate backoff time with exponential increase, capped at 60 seconds
        const backoffTime = Math.min(
          polling.currentRefresh * Math.pow(2, polling.retryCount) * 1000,
          60000,
        );

        log.debug(
          `Retry ${polling.retryCount}/${polling.maxRetries}, backoff time: ${backoffTime / 1000}s`,
        );

        polling.timeout = setTimeout(poll, backoffTime);
      }
    }
  };

  // Begin polling
  poll();

  // Set up the cleanup function
  currentPollCleanup = () => {
    polling.isActive = false;
    if (polling.timeout) {
      clearTimeout(polling.timeout);
      polling.timeout = -1;
    }
  };
};

const clearPendingSummaries = (
  logFile: string,
  getState: () => LogStore,
  setState: (state: Partial<LogStore>) => void,
) => {
  const pendingSampleSummaries = getState().pendingSampleSummaries;
  if ((pendingSampleSummaries?.samples.length || 0) > 0) {
    log.debug(`CLEAR PENDING: ${logFile}`);
    setState({
      pendingSampleSummaries: {
        samples: [],
        refresh: pendingSampleSummaries?.refresh || 2,
      },
    });
    getState().refreshLog();
  }
};

// Initialize store with API and optional initial states
export const initializeLogStore = (api: ClientAPI, initialState: LogState) => {
  useLogStore.getState().initializeStore(api, initialState);
};

export const useSampleSummaries = () => {
  const selectedLogSummary = useLogStore((state) => state.selectedLogSummary);
  const pendingSampleSummaries = useLogStore(
    (state) => state.pendingSampleSummaries,
  );

  return useMemo(() => {
    return mergeSampleSummaries(
      selectedLogSummary?.sampleSummaries || [],
      pendingSampleSummaries?.samples || [],
    );
  }, [selectedLogSummary, pendingSampleSummaries]);
};

export const useTotalSampleCount = () => {
  const sampleSummaries = useSampleSummaries();
  return useMemo(() => {
    return sampleSummaries.length;
  }, [sampleSummaries]);
};

export const useScore = () => {
  const selectedLogSummary = useLogStore((state) => state.selectedLogSummary);
  const sampleSummaries = useSampleSummaries();
  const score = useLogStore((state) => state.score);
  return useMemo(() => {
    if (score) {
      return score;
    } else if (selectedLogSummary) {
      return getDefaultScorer(selectedLogSummary, sampleSummaries);
    } else {
      return undefined;
    }
  }, [selectedLogSummary, sampleSummaries, score]);
};

export const useScores = () => {
  const selectedLogSummary = useLogStore((state) => state.selectedLogSummary);
  const sampleSummaries = useSampleSummaries();
  return useMemo(() => {
    if (!selectedLogSummary) {
      return [];
    }

    return getAvailableScorers(selectedLogSummary, sampleSummaries) || [];
  }, [selectedLogSummary, sampleSummaries]);
};

export const useEvalDescriptor = () => {
  const scores = useScores();
  const sampleSummaries = useSampleSummaries();
  return useMemo(() => {
    return scores ? createEvalDescriptor(scores, sampleSummaries) : null;
  }, [scores, sampleSummaries]);
};

export const useSampleDescriptor = () => {
  const evalDescriptor = useEvalDescriptor();
  const sampleSummaries = useSampleSummaries();
  const score = useScore();
  return useMemo(() => {
    return evalDescriptor && score
      ? createSamplesDescriptor(sampleSummaries, evalDescriptor, score)
      : undefined;
  }, [evalDescriptor, sampleSummaries, score]);
};

export const useFilteredSamples = () => {
  const evalDescriptor = useEvalDescriptor();
  const sampleSummaries = useSampleSummaries();
  const filter = useLogStore((state) => state.filter);
  const epoch = useLogStore((state) => state.epoch);
  const sort = useLogStore((state) => state.sort);
  const samplesDescriptor = useSampleDescriptor();
  const score = useScore();

  return useMemo(() => {
    // Apply filters
    const prefiltered =
      evalDescriptor && filter.value
        ? filterSamples(evalDescriptor, sampleSummaries, filter.value).result
        : sampleSummaries;

    // Filter epochs
    const filtered =
      epoch && epoch !== "all"
        ? prefiltered.filter((sample) => epoch === String(sample.epoch))
        : prefiltered;

    // Sort samples
    const sorted = samplesDescriptor
      ? sortSamples(sort, filtered, samplesDescriptor, score)
      : filtered;

    return [...sorted];
  }, [
    evalDescriptor,
    sampleSummaries,
    filter,
    epoch,
    sort,
    samplesDescriptor,
    score,
  ]);
};

export const useGroupBy = () => {
  const selectedLogSummary = useLogStore((state) => state.selectedLogSummary);
  const sort = useLogStore((state) => state.sort);
  const epoch = useLogStore((state) => state.epoch);
  return useMemo(() => {
    const epochs = selectedLogSummary?.eval?.config?.epochs || 1;
    if (epochs > 1) {
      if (byEpoch(sort) || epoch !== "all") {
        return "epoch";
      } else if (bySample(sort)) {
        return "sample";
      }
    }

    return "none";
  }, [selectedLogSummary, sort, epoch]);
};

export const useGroupByOrder = () => {
  const sort = useLogStore((state) => state.sort);
  return useMemo(() => {
    return sort === kSampleAscVal ||
      sort === kEpochAscVal ||
      sort === kScoreAscVal
      ? "asc"
      : "desc";
  }, [sort]);
};

export { useLogStore };
