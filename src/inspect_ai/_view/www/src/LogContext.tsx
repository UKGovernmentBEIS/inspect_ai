import {
  createContext,
  Dispatch,
  FC,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
} from "react";
import {
  ClientAPI,
  EvalSummary,
  PendingSamples,
  SampleSummary,
} from "./api/types";
import { useAppContext } from "./AppContext";
import {
  kDefaultSort,
  kEpochAscVal,
  kSampleAscVal,
  kScoreAscVal,
} from "./constants";
import { useLogsContext } from "./LogsContext";
import {
  createEvalDescriptor,
  createSamplesDescriptor,
  SamplesDescriptor,
} from "./samples/descriptor/samplesDescriptor";
import { EvalDescriptor } from "./samples/descriptor/types";
import { filterSamples } from "./samples/sample-tools/filters";
import {
  byEpoch,
  bySample,
  sortSamples,
} from "./samples/sample-tools/SortFilter";
import {
  getAvailableScorers,
  getDefaultScorer,
  ScorerInfo,
} from "./scoring/utils";
import { ScoreFilter, ScoreLabel } from "./types";
import { Timeout } from "./types/log";

// Define action types
type LogAction =
  | { type: "SET_FILTER"; payload: ScoreFilter }
  | { type: "SET_EPOCH"; payload: string }
  | { type: "SET_SORT"; payload: string }
  | { type: "SET_SCORE"; payload: ScoreLabel }
  | { type: "SELECT_SAMPLE"; payload: number }
  | { type: "SET_SELECTED_LOG_SUMMARY"; payload: EvalSummary }
  | { type: "RESET_FILTERING" }
  | { type: "SET_PENDING_SAMPLE_SUMMARIES"; payload: PendingSamples };

// Define the state shape
export interface LogState {
  selectedLogSummary?: EvalSummary;
  pendingSampleSummaries?: PendingSamples;
  selectedSampleIndex: number;
  filter: ScoreFilter;
  epoch: string;
  sort: string;
  score?: ScoreLabel;
}

// Initial state
const initialLogState: LogState = {
  selectedSampleIndex: -1,
  filter: {},
  epoch: "all",
  sort: kDefaultSort,
};

// Reducer function
const logsReducer = (state: LogState, action: LogAction): LogState => {
  switch (action.type) {
    case "SET_FILTER":
      return { ...state, filter: action.payload };
    case "SET_EPOCH":
      return { ...state, epoch: action.payload };
    case "SET_SORT":
      return { ...state, sort: action.payload };
    case "SET_SCORE":
      return { ...state, score: action.payload };
    case "SELECT_SAMPLE":
      return { ...state, selectedSampleIndex: action.payload };
    case "SET_SELECTED_LOG_SUMMARY":
      return { ...state, selectedLogSummary: action.payload };
    case "SET_PENDING_SAMPLE_SUMMARIES":
      return { ...state, pendingSampleSummaries: action.payload };
    case "RESET_FILTERING":
      return {
        ...state,
        score: undefined,
        epoch: "all",
        filter: {},
        sort: kDefaultSort,
      };
    default:
      return state;
  }
};

export interface LogContextType {
  state: LogState;
  dispatch: Dispatch<LogAction>;
  getState: () => { log: LogState };
  sampleSummaries: SampleSummary[];
  totalSampleCount: number;
  scores: ScorerInfo[];
  evalDescriptor?: EvalDescriptor;
  samplesDescriptor?: SamplesDescriptor;
  groupBy: "none" | "epoch" | "sample";
  groupByOrder: "asc" | "desc";
  refreshLog: () => Promise<void>;
  loadLog: (logFile: string) => Promise<void>;
}

const LogContext = createContext<LogContextType | undefined>(undefined);

interface LogProviderProps {
  initialState?: { log?: LogState };
  children: ReactNode;
  api: ClientAPI;
}

export const LogProvider: FC<LogProviderProps> = ({
  children,
  initialState,
  api,
}) => {
  const appContext = useAppContext();
  const logsContext = useLogsContext();

  const [state, dispatch] = useReducer(
    logsReducer,
    initialState
      ? { ...initialLogState, ...initialState.log }
      : initialLogState,
  );

  const getState = () => {
    return { log: state };
  };

  // Load a specific log file
  const loadLog = useCallback(
    async (logFileName: string) => {
      const logContents = await api.get_log_summary(logFileName);
      dispatch({ type: "SET_SELECTED_LOG_SUMMARY", payload: logContents });
      dispatch({ type: "RESET_FILTERING" });
    },
    [api, appContext.dispatch],
  );

  const refreshLog = useCallback(async () => {
    const file = logsContext.selectedLogFile;
    if (file) {
      const logContents = await api.get_log_summary(file);
      dispatch({ type: "SET_SELECTED_LOG_SUMMARY", payload: logContents });
    }
  }, [api]);

  useEffect(() => {
    // Only start polling if we have a selected log summary
    if (!state.selectedLogSummary) return;

    let isActive = true;
    let pollTimeout: Timeout | null = null;
    let hadPending = false;

    const clearPendingSummaries = () => {
      if ((state.pendingSampleSummaries?.samples.length || 0) > 0) {
        dispatch({
          type: "SET_PENDING_SAMPLE_SUMMARIES",
          payload: {
            samples: [],
            refresh: state.pendingSampleSummaries?.refresh || 2,
          },
        });
        refreshLog();
      }
    };

    const pollPendingSamples = async () => {
      // Don't bother polling if the API doesn't support it
      if (!api.get_log_pending_samples) return;

      try {
        // We need the log file name from somewhere - either pass it to context or get from logsContext
        const logFile = logsContext.selectedLogFile;
        if (!logFile) return;

        const pendingSamples = await api.get_log_pending_samples(
          logFile,
          state.pendingSampleSummaries?.etag,
        );

        if (!isActive) return;

        if (pendingSamples.status === "OK" && pendingSamples.pendingSamples) {
          dispatch({
            type: "SET_PENDING_SAMPLE_SUMMARIES",
            payload: pendingSamples.pendingSamples,
          });
          refreshLog();
          hadPending = true;
        } else if (pendingSamples.status === "NotFound") {
          if (hadPending) {
            refreshLog();
          }
          clearPendingSummaries();
          // stop polling
          isActive = false;
        }

        if (isActive) {
          pollTimeout = setTimeout(
            pollPendingSamples,
            (state.pendingSampleSummaries?.refresh || 2) * 1000,
          );
        }
      } catch (error) {
        console.error("Error polling pending samples:", error);
        if (isActive) {
          pollTimeout = setTimeout(
            pollPendingSamples,
            Math.min(
              (state.pendingSampleSummaries?.refresh || 2) * 2 * 1000,
              60000,
            ),
          );
        }
      }
    };

    // Start polling when effect runs
    pollPendingSamples();

    // Clean up when effect is done
    return () => {
      isActive = false;
      if (pollTimeout) {
        clearTimeout(pollTimeout);
      }
    };
  }, [
    // These dependencies will trigger the effect to restart
    state.selectedLogSummary,
    state.pendingSampleSummaries?.etag,
    state.pendingSampleSummaries?.refresh,
    api.get_log_pending_samples,
    logsContext.selectedLogFile,
  ]);

  const sampleSummaries = useMemo(() => {
    const logSamples = state.selectedLogSummary?.sampleSummaries || [];
    const pendingSamples = state.pendingSampleSummaries?.samples || [];
    const result = mergeSampleSummaries(logSamples, pendingSamples);
    return result;
  }, [
    state.selectedLogSummary?.sampleSummaries,
    state.pendingSampleSummaries?.samples,
  ]);

  const currentScore = useMemo(() => {
    if (state.score) {
      return state.score;
    } else if (state.selectedLogSummary) {
      return getDefaultScorer(state.selectedLogSummary, sampleSummaries);
    }
  }, [state.selectedLogSummary, sampleSummaries]);

  const scores = useMemo(() => {
    if (!state.selectedLogSummary) {
      return [];
    }
    return getAvailableScorers(state.selectedLogSummary, sampleSummaries) || [];
  }, [state.selectedLogSummary, sampleSummaries]);

  const evalDescriptor = useMemo(() => {
    const result = createEvalDescriptor(scores, sampleSummaries);
    return result;
  }, [state.selectedLogSummary, sampleSummaries, scores]);

  const samplesDescriptor = useMemo(() => {
    if (!state.selectedLogSummary) {
      return undefined;
    }
    const descriptor = evalDescriptor
      ? createSamplesDescriptor(sampleSummaries, evalDescriptor, currentScore)
      : undefined;
    return descriptor;
  }, [evalDescriptor, state.score, state.selectedLogSummary, sampleSummaries]);

  const filteredSampleSummaries = useMemo(() => {
    const samples = sampleSummaries || [];

    const { result: prefiltered } =
      evalDescriptor && state.filter?.value
        ? filterSamples(evalDescriptor, samples, state.filter.value)
        : { result: samples };

    const filtered = prefiltered.filter((sample) => {
      // Filter by epoch if specified
      if (state.epoch && state.epoch !== "all") {
        if (state.epoch !== String(sample.epoch)) {
          return false;
        }
      }
      return true;
    });

    // Sort the samples
    if (samplesDescriptor) {
      const sorted = sortSamples(
        state.sort,
        filtered,
        samplesDescriptor,
        currentScore,
      );
      return sorted;
    } else {
      return filtered;
    }
  }, [
    sampleSummaries,
    evalDescriptor,
    samplesDescriptor,
    state.filter,
    state.sort,
    currentScore,
  ]);

  const groupBy = useMemo(() => {
    // Set the grouping
    let grouping: "none" | "epoch" | "sample" = "none";
    if (
      state.selectedLogSummary?.eval?.config?.epochs &&
      (state.selectedLogSummary?.eval?.config?.epochs || 1) > 1
    ) {
      if (byEpoch(state.sort) || state.epoch !== "all") {
        grouping = "epoch";
      } else if (bySample(state.sort)) {
        grouping = "sample";
      }
    }
    return grouping;
  }, [state.selectedLogSummary, samplesDescriptor]);

  const groupByOrder = useMemo(() => {
    return state.sort === kSampleAscVal ||
      state.sort === kEpochAscVal ||
      state.sort === kScoreAscVal
      ? "asc"
      : "desc";
  }, [state.sort]);

  const totalSampleCount = useMemo(() => {
    return (
      (state.pendingSampleSummaries?.samples.length || 0) +
      (state.selectedLogSummary?.sampleSummaries.length || 0)
    );
  }, [
    state.pendingSampleSummaries?.samples,
    state.selectedLogSummary?.sampleSummaries,
  ]);

  return (
    <LogContext.Provider
      value={{
        state,
        dispatch,
        getState,
        sampleSummaries: filteredSampleSummaries,
        scores,
        evalDescriptor,
        samplesDescriptor,
        groupBy,
        groupByOrder,
        refreshLog,
        loadLog,
        totalSampleCount,
      }}
    >
      {children}
    </LogContext.Provider>
  );
};

// Custom hook to access log context
export const useLogContext = (): LogContextType => {
  const context = useContext(LogContext);
  if (!context) {
    throw new Error("useLogContext must be used within a LogProvider");
  }
  return context;
};

// Function to merge log samples with pending samples
const mergeSampleSummaries = (
  logSamples: SampleSummary[],
  pendingSamples: SampleSummary[],
): SampleSummary[] => {
  // Create a map of existing sample IDs to avoid duplicates
  const existingSampleIds = new Set(
    logSamples.map((sample) => `${sample.id}-${sample.epoch}`),
  );

  // Filter out any pending samples that already exist in the log
  const uniquePendingSamples = pendingSamples.filter(
    (sample) => !existingSampleIds.has(`${sample.id}-${sample.epoch}`),
  );

  // Combine and return all samples
  return [...logSamples, ...uniquePendingSamples];
};
