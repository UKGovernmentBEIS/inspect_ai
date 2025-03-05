import { SampleSummary } from "../api/types";
import { kSampleMessagesTabId } from "../constants";
import { RunningSampleData, SampleState, SampleStatus } from "../types";
import { EvalSample } from "../types/log";
import { resolveAttachments } from "../utils/attachments";
import { createLogger } from "../utils/logger";
import { createSamplePolling } from "./samplePolling";
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

    // Running data
    setRunningSampleData: (data: RunningSampleData) => void;
    clearRunningSampleData: () => void;

    // Loading
    loadSample: (
      logFile: string,
      sampleSummary: SampleSummary,
    ) => Promise<void>;
  };
}

const initialState: SampleState = {
  selectedSample: undefined,
  sampleStatus: "ok",
  sampleError: undefined,
  runningSampleData: undefined,
};

export const createSampleSlice = (
  set: (fn: (state: StoreState) => void) => void,
  get: () => StoreState,
  _store: any,
) => {
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

  // The sample poller
  const samplePolling = createSamplePolling(get, set);

  return {
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
      setSampleStatus: (status: "ok" | "loading" | "error") =>
        set((state) => {
          state.sample.sampleStatus = status;
        }),
      setSampleError: (error: Error | undefined) =>
        set((state) => {
          state.sample.sampleError = error;
        }),
      setRunningSampleData: (data: RunningSampleData) =>
        set((state) => {
          state.sample.runningSampleData = data;
        }),
      clearRunningSampleData: () =>
        set((state) => {
          state.sample.runningSampleData = undefined;
        }),

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
              const migratedSample = migrateOldSample(sample);
              sampleActions.setSelectedSample(migratedSample);
            } else {
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
          sampleActions.setSampleStatus("ok");
        } catch (e) {
          sampleActions.setSampleError(e as Error);
          sampleActions.setSampleStatus("error");
        }
      },
    },
  } as const;
};

export const initializeSampleSlice = (
  set: (fn: (state: StoreState) => void) => void,
  restoreState?: Partial<SampleState>,
) => {
  set((state) => {
    state.sample = { ...initialState };
    if (restoreState) {
      if (restoreState.selectedSample) {
        state.sample.selectedSample = restoreState.selectedSample;
      }

      if (restoreState.sampleError) {
        state.sample.sampleError = restoreState.sampleError;
      }

      if (restoreState.sampleStatus) {
        state.sample.sampleStatus = restoreState.sampleStatus;
      }

      if (restoreState.runningSampleData) {
        state.sample.runningSampleData = restoreState.runningSampleData;
      }
    }
  });
};
