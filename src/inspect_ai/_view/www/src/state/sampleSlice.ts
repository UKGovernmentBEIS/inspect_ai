import { EvalSample } from "../@types/log";
import { SampleState, SampleStatus } from "../app/types";
import { SampleSummary } from "../client/api/types";
import { kSampleMessagesTabId } from "../constants";
import { createLogger } from "../utils/logger";
import { createSamplePolling } from "./samplePolling";
import { resolveSample } from "./sampleUtils"; // Import the shared utility
import { StoreState } from "./store";

const log = createLogger("sampleSlice");

export interface SampleSlice {
  sample: SampleState;
  sampleActions: {
    // The actual sample data
    setSelectedSample: (sample: EvalSample) => void;
    clearSelectedSample: () => void;
    setSampleStatus: (status: SampleStatus) => void;
    setSampleError: (error: Error | undefined) => void;

    // Loading
    loadSample: (
      logFile: string,
      sampleSummary: SampleSummary,
    ) => Promise<void>;

    pollSample: (
      logFile: string,
      sampleSummary: SampleSummary,
    ) => Promise<void>;
  };
}

const initialState: SampleState = {
  selectedSample: undefined,
  sampleStatus: "ok",
  sampleError: undefined,

  // The resolved events
  runningEvents: [],
};

export const createSampleSlice = (
  set: (fn: (state: StoreState) => void) => void,
  get: () => StoreState,
  _store: any,
): [SampleSlice, () => void] => {
  // The sample poller
  const samplePolling = createSamplePolling(get, set);

  const slice = {
    // Actions
    sample: initialState,
    sampleActions: {
      setSelectedSample: (sample: EvalSample) => {
        set((state) => {
          state.sample.selectedSample = sample;
        });
        if (sample.events.length < 1) {
          // If there are no events, use the messages tab as the default
          get().appActions.setSampleTab(kSampleMessagesTabId);
        }
      },
      clearSelectedSample: () =>
        set((state) => {
          state.sample.selectedSample = undefined;
        }),
      setSampleStatus: (status: SampleStatus) =>
        set((state) => {
          state.sample.sampleStatus = status;
        }),
      setSampleError: (error: Error | undefined) =>
        set((state) => {
          state.sample.sampleError = error;
        }),
      pollSample: async (logFile: string, sampleSummary: SampleSummary) => {
        // Poll running sample
        const state = get();
        if (state.log.loadedLog && state.sample.selectedSample) {
          samplePolling.startPolling(logFile, sampleSummary);
        }
      },
      loadSample: async (logFile: string, sampleSummary: SampleSummary) => {
        const sampleActions = get().sampleActions;

        sampleActions.setSampleError(undefined);
        sampleActions.setSampleStatus("loading");
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
              const migratedSample = resolveSample(sample);
              sampleActions.setSelectedSample(migratedSample);
              sampleActions.setSampleStatus("ok");
            } else {
              sampleActions.setSampleStatus("error");
              throw new Error(
                "Unable to load sample - an unknown error occurred",
              );
            }
          } else {
            log.debug(
              `POLLING RUNNING SAMPLE: ${sampleSummary.id}-${sampleSummary.epoch}`,
            );

            // Poll running sample
            samplePolling.startPolling(logFile, sampleSummary);
          }
        } catch (e) {
          sampleActions.setSampleError(e as Error);
          sampleActions.setSampleStatus("error");
        }
      },
    },
  } as const;

  const cleanup = () => {
    samplePolling.cleanup();
  };
  return [slice, cleanup];
};

export const initializeSampleSlice = (
  set: (fn: (state: StoreState) => void) => void,
) => {
  set((state) => {
    if (!state.sample) {
      state.sample = initialState;
    }
  });
};
