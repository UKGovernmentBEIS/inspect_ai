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
  useRef,
} from "react";
import { ClientAPI, SampleSummary } from "../api/types";
import { sampleDataAdapter } from "../samples/sampleDataAdapter";
import { RunningSampleData, SampleState } from "../types";
import { EvalSample } from "../types/log";
import { resolveAttachments } from "../utils/attachments";
import { createLogger } from "../utils/logger";
import { createPolling, Polling } from "../utils/polling";
import { useLogContext } from "./LogContext";

// Define action types
type SampleAction =
  | { type: "SET_SELECTED_SAMPLE"; payload: EvalSample | undefined }
  | { type: "CLEAR_SELECTED_SAMPLE" }
  | { type: "SET_LOADING"; payload: boolean }
  | { type: "SET_ERROR"; payload: Error }
  | { type: "SET_RUNNING_SAMPLE_DATA"; payload: RunningSampleData | undefined }
  | { type: "RESET_SAMPLE" };

// Create the reducer function
const sampleReducer = (
  state: SampleState,
  action: SampleAction,
): SampleState => {
  switch (action.type) {
    case "SET_SELECTED_SAMPLE":
      return { ...state, selectedSample: action.payload };
    case "CLEAR_SELECTED_SAMPLE":
      return { ...state, selectedSample: undefined };
    case "SET_RUNNING_SAMPLE_DATA":
      return { ...state, runningSampleData: action.payload };
    case "SET_LOADING": {
      const status = action.payload ? "loading" : "ok";
      return { ...state, sampleStatus: status, sampleError: undefined };
    }
    case "SET_ERROR":
      return {
        ...state,
        sampleStatus: "error",
        sampleError: action.payload,
        selectedSample: undefined,
      };
    case "RESET_SAMPLE":
      return {
        selectedSample: undefined,
        sampleStatus: "loading",
        sampleError: undefined,
        runningSampleData: undefined,
      };
    default:
      return state;
  }
};

// Initial state
const initialSampleState: SampleState = {
  selectedSample: undefined,
  sampleStatus: "loading",
  sampleError: undefined,
  runningSampleData: undefined,
};

// Create the context with state and dispatch
interface SampleContextType {
  state: SampleState;
  dispatch: Dispatch<SampleAction>;
  getState: () => { sample: SampleState };
}

const SampleContext = createContext<SampleContextType | undefined>(undefined);

interface SampleProviderProps {
  initialState?: { sample?: SampleState };
  children: ReactNode;
  api: ClientAPI;
}

export const SampleProvider: FC<SampleProviderProps> = ({
  children,
  api,
  initialState,
}) => {
  const log = useMemo(() => {
    return createLogger("SampleContext");
  }, []);

  // Use reducer for state management
  const [state, dispatch] = useReducer(
    sampleReducer,
    initialState?.sample || initialSampleState,
  );

  // Refs
  const pollingRef = useRef<Polling>(null);

  // Context hooks
  const logContext = useLogContext();

  // Helper function for old sample migration
  const migrateOldSample = (sample: any) => {
    if (sample.transcript) {
      sample.events = sample.transcript.events;
      sample.attachments = sample.transcript.content;
    }
    sample.attachments = sample.attachments || {};
    sample.input = resolveAttachments(sample.input, sample.attachments);
    sample.messages = resolveAttachments(sample.messages, sample.attachments);
    sample.events = resolveAttachments(sample.events, sample.attachments);
    sample.attachments = {};
    return sample;
  };

  // Poll for sample data
  const pollForSampleData = useCallback(
    (logFile: string, summary: SampleSummary) => {
      // Clean up any existing polling
      if (pollingRef.current) {
        pollingRef.current.stop();
      }

      const pollCallback = async () => {
        if (!api.get_log_sample_data) {
          return false; // Stop polling
        }

        log.debug(`GET RUNNING SAMPLE: ${summary.id}-${summary.epoch}`);
        const sampleDataResponse = await api.get_log_sample_data(
          logFile,
          summary.id,
          summary.epoch,
        );

        if (sampleDataResponse?.status === "NotFound") {
          // Stop polling
          return false;
        }

        if (
          sampleDataResponse?.status === "OK" &&
          sampleDataResponse.sampleData
        ) {
          const adapter = sampleDataAdapter();
          adapter.addData(sampleDataResponse.sampleData);
          const runningData = { events: adapter.resolvedEvents(), summary };
          dispatch({ type: "SET_RUNNING_SAMPLE_DATA", payload: runningData });
        }
        // Continue polling
        return true;
      };

      // Create and start the polling mechanism
      const name = `${logFile}:${summary.id}-${summary.epoch}`;
      pollingRef.current = createPolling(name, pollCallback, {
        maxRetries: 10,
        interval: 2,
      });

      pollingRef.current.start();
    },
    [api.get_log_sample_data, dispatch, log],
  );

  // Cancel polling
  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        pollingRef.current.stop();
      }
    };
  }, []);

  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        pollingRef.current.stop();
      }
    };
  }, [logContext.selectedLogFile]);

  // Cancel polling
  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        pollingRef.current.stop();
      }
    };
  }, [logContext.state.selectedSampleIndex]);

  // Load a specific sample
  const loadSample = useCallback(
    async (summary: SampleSummary) => {
      if (!logContext.selectedLogFile) {
        return;
      }

      dispatch({ type: "SET_LOADING", payload: true });

      try {
        // If a sample is completed, but we're still polling,
        // this means that the sample hasn't been flushed, so we should
        // continue to show the live view until the sample is flushed
        if (summary.completed !== false) {
          log.debug(`LOADING COMPLETED SAMPLE: ${summary.id}-${summary.epoch}`);
          const sample = await api.get_log_sample(
            logContext.selectedLogFile,
            summary.id,
            summary.epoch,
          );
          if (sample) {
            const migratedSample = migrateOldSample(sample);
            dispatch({ type: "SET_SELECTED_SAMPLE", payload: migratedSample });
          } else {
            throw new Error(
              "Unable to load sample - an unknown error occurred.",
            );
          }
        } else {
          log.debug(`POLLING RUNNING SAMPLE: ${summary.id}-${summary.epoch}`);
          pollForSampleData(logContext.selectedLogFile, summary);
        }

        dispatch({ type: "SET_LOADING", payload: false });
      } catch (e) {
        dispatch({ type: "SET_ERROR", payload: e as Error });
      }
    },
    [logContext.selectedLogFile, pollForSampleData],
  );

  // Clear the selected sample when log file changes
  useEffect(() => {
    if (
      !logContext.selectedLogFile ||
      logContext.state.selectedSampleIndex === -1
    ) {
      dispatch({ type: "SET_SELECTED_SAMPLE", payload: undefined });
    }
  }, [logContext.state.selectedSampleIndex, logContext.selectedLogFile]);

  // Load selected sample when index changes
  const selectedSampleSummary = useMemo(() => {
    return logContext.sampleSummaries[logContext.state.selectedSampleIndex];
  }, [logContext.state.selectedSampleIndex, logContext.sampleSummaries]);

  useEffect(() => {
    if (selectedSampleSummary) {
      loadSample(selectedSampleSummary);
    } else {
      dispatch({ type: "RESET_SAMPLE" });
    }
  }, [selectedSampleSummary]);

  const getState = () => {
    return { sample: state };
  };

  // Context value
  const contextValue = {
    state,
    dispatch,
    getState,
  };

  return (
    <SampleContext.Provider value={contextValue}>
      {children}
    </SampleContext.Provider>
  );
};

// Custom hook to use the sample context
export const useSampleContext = () => {
  const context = useContext(SampleContext);
  if (context === undefined) {
    throw new Error("useSampleContext must be used within a SampleProvider");
  }
  return context;
};
