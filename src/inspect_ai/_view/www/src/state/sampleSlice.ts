import { EvalSample } from "../@types/log";
import { SampleState, SampleStatus } from "../app/types";
import { SampleSummary } from "../client/api/types";
import { kSampleMessagesTabId } from "../constants";
import { createLogger } from "../utils/logger";
import { createSamplePolling } from "./samplePolling";
import { resolveSample } from "./sampleUtils";
import { StoreState } from "./store";
import { isLargeSample } from "./store_filter";

const log = createLogger("sampleSlice");

// Create a module-level ref to store large sample objects
let selectedSampleRef: { current: EvalSample | undefined } = {
  current: undefined,
};

export interface SampleSlice {
  sample: SampleState;
  sampleActions: {
    // The actual sample data
    setSelectedSample: (sample: EvalSample) => void;
    getSelectedSample: () => EvalSample | undefined;
    clearSelectedSample: () => void;
    setSampleStatus: (status: SampleStatus) => void;
    setSampleError: (error: Error | undefined) => void;

    setCollapsedEvents: (collapsed: Set<string>) => void;
    collapseEvent: (id: string, collapsed: boolean) => void;
    clearCollapsedEvents: () => void;

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
  // Store ID for all samples (used for triggering renders)
  sample_identifier: undefined,
  // Store the actual sample object for small samples
  selectedSampleObject: undefined,
  // Flag to indicate where the sample is stored
  sampleInState: false,
  sampleStatus: "ok",
  sampleError: undefined,

  // signals that the sample needs to be reloaded
  sampleNeedsReload: 0,

  // The resolved events
  runningEvents: [],
  collapsedEvents: new Set<string>(),
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
        const isLarge = isLargeSample(sample);

        // Update state based on sample size
        set((state) => {
          state.sample.sample_identifier = {
            id: sample.id,
            epoch: sample.epoch,
          };
          state.sample.sampleInState = !isLarge;

          // Only store in state if it's small
          if (!isLarge) {
            state.sample.selectedSampleObject = sample;
            // Clear ref if using state
            selectedSampleRef.current = undefined;
          } else {
            // Use ref for large objects
            state.sample.selectedSampleObject = undefined;
            selectedSampleRef.current = sample;
          }
        });

        if (sample.events.length < 1) {
          // If there are no events, use the messages tab as the default
          get().appActions.setSampleTab(kSampleMessagesTabId);
        }
      },
      getSelectedSample: () => {
        const state = get().sample;
        // Return from state if stored there, otherwise from ref
        return state.sampleInState
          ? state.selectedSampleObject
          : selectedSampleRef.current;
      },
      clearSelectedSample: () => {
        // Clear both the ref and the state
        selectedSampleRef.current = undefined;
        set((state) => {
          state.sample.sample_identifier = undefined;
          state.sample.selectedSampleObject = undefined;
          state.sample.sampleInState = false;
        });
      },
      setSampleStatus: (status: SampleStatus) =>
        set((state) => {
          state.sample.sampleStatus = status;
        }),
      setSampleError: (error: Error | undefined) =>
        set((state) => {
          state.sample.sampleError = error;
        }),
      setCollapsedEvents: (collapsed: Set<string>) => {
        set((state) => {
          state.sample.collapsedEvents = collapsed;
        });
      },
      clearCollapsedEvents: () => {
        set((state) => {
          state.sample.collapsedEvents = new Set<string>();
        });
      },
      collapseEvent: (id: string, collapsed: boolean) => {
        set((state) => {
          if (collapsed) {
            state.sample.collapsedEvents.add(id);
          } else {
            state.sample.collapsedEvents.delete(id);
          }
        });
      },
      pollSample: async (logFile: string, sampleSummary: SampleSummary) => {
        // Poll running sample
        const state = get();
        const sampleExists = state.sample.sampleInState
          ? !!state.sample.selectedSampleObject
          : !!selectedSampleRef.current;

        if (state.log.loadedLog && sampleExists) {
          samplePolling.startPolling(logFile, sampleSummary);
        }
      },
      loadSample: async (logFile: string, sampleSummary: SampleSummary) => {
        const sampleActions = get().sampleActions;

        sampleActions.setSampleError(undefined);
        sampleActions.setSampleStatus("loading");
        const state = get();

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
            log.debug(
              `LOADED COMPLETED SAMPLE: ${sampleSummary.id}-${sampleSummary.epoch}`,
            );
            if (sample) {
              const migratedSample = resolveSample(sample);

              sampleActions.clearCollapsedEvents();
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
    // Clear the ref when cleaning up
    selectedSampleRef.current = undefined;
  };
  return [slice, cleanup];
};

export const handleRehydrate = (state: StoreState) => {
  // Increment the reload counter if the sample is not in state
  if (!state.sample.sampleInState) {
    state.sample.sampleNeedsReload = state.sample.sampleNeedsReload + 1;
  }
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
