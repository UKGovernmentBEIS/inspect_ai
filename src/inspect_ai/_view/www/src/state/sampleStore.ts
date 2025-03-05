import { useEffect } from "react";
import { create } from "zustand";
import { immer } from "zustand/middleware/immer";
import { ClientAPI, SampleSummary } from "../api/types";
import { sampleDataAdapter } from "../samples/sampleDataAdapter";
import { RunningSampleData, SampleState, SampleStatus } from "../types";
import { EvalSample } from "../types/log";
import { resolveAttachments } from "../utils/attachments";
import { createLogger } from "../utils/logger";
import { createPolling, Polling } from "../utils/polling";
import { useLogsStore } from "./logsStore";
import { useFilteredSamples, useLogStore } from "./logStore";

// Define the store type with proper typing
interface SampleStore extends SampleState {
  // Getter method
  getState: () => { sample: SampleState };

  // The api
  api: ClientAPI | null;

  // The actual sample data
  setSelectedSample: (sample: EvalSample) => void;
  clearSelectedSample: () => void;

  // sample loading
  loadSample: (logFile: string, sampleSummary: SampleSummary) => Promise<void>;
  setSampleStatus: (status: SampleStatus) => void;
  setSampleError: (error: Error | undefined) => void;
  setRunningSampleData: (data: RunningSampleData) => void;
  clearRunningSampleData: () => void;

  // sample polling
  activePolling: Polling | null;
  pollForSampleData: (logFile: string, summary: SampleSummary) => void;
  stopPolling: () => void;

  // Initialize the store
  initializeStore: (
    api: ClientAPI,
    initialState?: Partial<SampleState>,
  ) => void;
  // Reset the entire store
  resetStore: () => void;
}

const initialState: SampleState = {
  selectedSample: undefined,
  sampleStatus: "ok",
  sampleError: undefined,
  runningSampleData: undefined,
};

// Create the store with proper typing for immer
export const useSampleStore = create<SampleStore>()(
  immer((set, get) => {
    // Migrates old versions of samples to the new structure
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

    return {
      // Initial state
      ...initialState,
      // Initialize api as null
      api: null,
      // Getter method
      getState: () => ({
        sample: {
          selectedSample: get().selectedSample,
          sampleStatus: get().sampleStatus,
          sampleError: get().sampleError,
          runningSampleData: get().runningSampleData,
        },
      }),
      // Actions
      setSelectedSample: (sample: EvalSample) =>
        set((state) => {
          state.selectedSample = sample;
        }),
      clearSelectedSample: () =>
        set((state) => {
          state.selectedSample = undefined;
        }),
      setSampleStatus: (status: "ok" | "loading" | "error") =>
        set((state) => {
          state.sampleStatus = status;
        }),
      setSampleError: (error: Error | undefined) =>
        set((state) => {
          state.sampleError = error;
        }),
      setRunningSampleData: (data: RunningSampleData) =>
        set((state) => {
          state.runningSampleData = data;
        }),
      clearRunningSampleData: () =>
        set((state) => {
          state.runningSampleData = undefined;
        }),

      loadSample: async (logFile, sampleSummary) => {
        const log = createLogger("sampleStore");
        get().setSampleError(undefined);
        get().setSampleStatus("loading");
        try {
          if (sampleSummary.completed !== false) {
            log.debug(
              `LOADING COMPLETED SAMPLE: ${sampleSummary.id}-${sampleSummary.epoch}`,
            );
            const sample = await get().api?.get_log_sample(
              logFile,
              sampleSummary.id,
              sampleSummary.epoch,
            );
            if (sample) {
              const migratedSample = migrateOldSample(sample);
              get().setSelectedSample(migratedSample);
            } else {
              throw new Error(
                "Unable to load sample - an unknown error occurred",
              );
            }
          } else {
            log.debug(
              `POLLING RUNNING SAMPLE: ${sampleSummary.id}-${sampleSummary.epoch}`,
            );

            get().pollForSampleData(logFile, sampleSummary);
          }
          get().setSampleStatus("ok");
        } catch (e) {
          get().setSampleError(e as Error);
          get().setSampleStatus("error");
        }
      },

      activePolling: null,

      pollForSampleData: (logFile, summary) => {
        const log = createLogger("sampleStore");

        // Stop any existing polling first
        get().stopPolling();

        log.debug(`POLLING RUNNING SAMPLE: ${summary.id}-${summary.epoch}`);

        // Create the polling callback
        const pollCallback = async () => {
          const api = get().api;
          if (!api) {
            throw new Error("Required API is missing");
          }

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
            get().setRunningSampleData(runningData);
          }
          // Continue polling
          return true;
        };

        // Create the polling instance
        const name = `${logFile}:${summary.id}-${summary.epoch}`;
        const polling = createPolling(name, pollCallback, {
          maxRetries: 10,
          interval: 2, // 2 seconds
        });

        // Store the polling instance and start it
        set((state) => {
          state.activePolling = polling;
        });

        polling.start();
      },

      stopPolling: () => {
        const activePolling = get().activePolling;
        if (activePolling) {
          activePolling.stop();
        }

        set((state) => {
          state.activePolling = null;
        });
      },

      // Reset the entire store
      resetStore: () => {
        get().stopPolling();
        set(() => ({ ...initialState, api: get().api }));
      },
      initializeStore: (
        api: ClientAPI,
        initialSampleState?: Partial<SampleState>,
      ) => {
        set((state) => {
          state.api = api;
          if (initialSampleState) {
            // Safely merge the initial state
            if (initialSampleState.selectedSample !== undefined)
              state.selectedSample = initialSampleState.selectedSample;
            if (initialSampleState.sampleStatus !== undefined)
              state.sampleStatus = initialSampleState.sampleStatus;
            if (initialSampleState.sampleError !== undefined)
              state.sampleError = initialSampleState.sampleError;
            if (initialSampleState.runningSampleData !== undefined)
              state.runningSampleData = initialSampleState.runningSampleData;
          }
        });
      },
    };
  }),
);

// Initialize store with API and optional initial states
export const initializeSampleStore = (
  api: ClientAPI,
  initialState?: SampleState,
) => {
  useSampleStore.getState().initializeStore(api, initialState);
};

export function useLoadSample() {
  return (logFile: string, sampleSummary: SampleSummary) => {
    if (logFile && sampleSummary) {
      useSampleStore.getState().loadSample(logFile, sampleSummary);
    } else {
      throw new Error("Can't load samples when there is no log file");
    }
  };
}

export function useSampleLoader() {
  const selectedLogFile = useLogsStore((state) => state.getSelectedLogFile());
  const selectedSampleIndex = useLogStore((state) => state.selectedSampleIndex);
  const sampleSummaries = useFilteredSamples();
  const { loadSample, stopPolling } = useSampleStore();

  useEffect(() => {
    // Clear sample when log file changes or no sample is selected
    if (!selectedLogFile || selectedSampleIndex === -1) {
      useSampleStore.getState().clearSelectedSample();
      useSampleStore.getState().stopPolling(); // Stop polling when selection changes
      return;
    }
  }, [
    selectedSampleIndex,
    selectedLogFile,
    sampleSummaries,
    loadSample,
    stopPolling,
  ]);
}
