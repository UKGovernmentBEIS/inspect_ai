import { EvalSample } from "../@types/log";
import { Event, SampleState, SampleStatus } from "../app/types";
import { kSampleMessagesTabId } from "../constants";
import {
  cleanupSamplePolling,
  getSamplePolling,
} from "./samplePollingInstance";
import { StoreState } from "./store";
import { isLargeSample } from "./store_filter";

// Create a module-level ref to store large sample objects
let selectedSampleRef: { current: EvalSample | undefined } = {
  current: undefined,
};

export const kDefaultExcludeEvents = [
  "sample_init",
  "sandbox",
  "state",
  "store",
];

export interface SampleSlice {
  sample: SampleState;
  sampleActions: {
    // The actual sample data
    setSelectedSample: (sample: EvalSample, logFile: string) => void;
    getSelectedSample: () => EvalSample | undefined;
    clearSelectedSample: () => void;

    setSampleStatus: (status: SampleStatus) => void;
    setSampleError: (error: Error | undefined) => void;

    setCollapsedEvents: (
      scope: string,
      collapsed: Record<string, boolean>,
    ) => void;
    collapseEvent: (scope: string, id: string, collapsed: boolean) => void;
    clearCollapsedEvents: () => void;

    setCollapsedIds: (key: string, collapsed: Record<string, true>) => void;
    collapseId: (key: string, id: string, collapsed: boolean) => void;
    clearCollapsedIds: (key: string) => void;
    setCollapsedMode: (mode: "collapsed" | "expanded" | null) => void;

    setFilteredEventTypes: (types: string[]) => void;

    setVisiblePopover: (id: string) => void;
    clearVisiblePopover: () => void;

    setSelectedOutlineId: (id: string) => void;
    clearSelectedOutlineId: () => void;

    // Used by useSampleLoader to clear state for running samples
    clearSampleForPolling: (
      logFile: string,
      id: number | string,
      epoch: number,
    ) => void;

    // Used by useSampleLoader to set identifier before loading
    setSampleIdentifier: (
      logFile: string,
      id: number | string,
      epoch: number,
    ) => void;

    // Used by samplePolling to update running events
    setRunningEvents: (events: Event[]) => void;
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

  visiblePopover: undefined,

  // signals that the sample needs to be reloaded
  sampleNeedsReload: 0,

  // The resolved events
  runningEvents: [],
  collapsedEvents: null,
  collapsedMode: null,
  eventFilter: {
    filteredTypes: [...kDefaultExcludeEvents],
  },

  collapsedIdBuckets: {},
  selectedOutlineId: undefined,
};

export const createSampleSlice = (
  set: (fn: (state: StoreState) => void) => void,
  get: () => StoreState,
  _store: any,
): [SampleSlice, () => void] => {
  const slice = {
    // Actions
    sample: initialState,
    sampleActions: {
      setSelectedSample: (sample: EvalSample, logFile: string) => {
        const isLarge = isLargeSample(sample);

        // Update state based on sample size
        set((state) => {
          state.sample.sample_identifier = {
            id: sample.id,
            epoch: sample.epoch,
            logFile: logFile,
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
        getSamplePolling().stopPolling();
        selectedSampleRef.current = undefined;
        set((state) => {
          state.sample.sample_identifier = undefined;
          state.sample.selectedSampleObject = undefined;
          state.sample.sampleInState = false;
          state.sample.runningEvents = [];
          state.sample.sampleStatus = "ok";
          state.log.selectedSampleHandle = undefined;
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
      setCollapsedEvents: (
        scope: string,
        collapsed: Record<string, boolean>,
      ) => {
        set((state) => {
          if (state.sample.collapsedEvents === null) {
            state.sample.collapsedEvents = {};
          }
          state.sample.collapsedEvents[scope] = collapsed;
        });
      },
      clearCollapsedEvents: () => {
        set((state) => {
          if (state.sample.collapsedEvents !== null) {
            state.sample.collapsedEvents = null;
          }
          state.sample.collapsedMode = null;
        });
      },
      collapseEvent: (scope: string, id: string, collapsed: boolean) => {
        set((state) => {
          if (state.sample.collapsedEvents === null) {
            state.sample.collapsedEvents = {};
          }
          if (!state.sample.collapsedEvents[scope]) {
            state.sample.collapsedEvents[scope] = {};
          }

          if (collapsed) {
            state.sample.collapsedEvents[scope][id] = true;
          } else {
            delete state.sample.collapsedEvents[scope][id];
          }
        });
      },
      setCollapsedIds: (key: string, collapsed: Record<string, true>) => {
        set((state) => {
          state.sample.collapsedIdBuckets[key] = collapsed;
        });
      },
      collapseId: (key: string, id: string, collapsed: boolean) => {
        set((state) => {
          if (state.sample.collapsedIdBuckets[key] === undefined) {
            state.sample.collapsedIdBuckets[key] = {};
          }
          if (collapsed) {
            state.sample.collapsedIdBuckets[key][id] = true;
          } else {
            delete state.sample.collapsedIdBuckets[key][id];
          }
        });
      },
      clearCollapsedIds: (key: string) => {
        set((state) => {
          delete state.sample.collapsedIdBuckets[key];
        });
      },
      setCollapsedMode: (mode: "collapsed" | "expanded" | null) => {
        set((state) => {
          state.sample.collapsedMode = mode;
        });
      },
      setFilteredEventTypes: (types: string[]) => {
        set((state) => {
          state.sample.eventFilter.filteredTypes = types;
        });
      },
      setVisiblePopover: (id: string) => {
        set((state) => {
          state.sample.visiblePopover = id;
        });
      },
      clearVisiblePopover: () => {
        set((state) => {
          state.sample.visiblePopover = undefined;
        });
      },
      setSelectedOutlineId: (id: string) => {
        set((state) => {
          state.sample.selectedOutlineId = id;
        });
      },
      clearSelectedOutlineId: () => {
        set((state) => {
          state.sample.selectedOutlineId = undefined;
        });
      },
      clearSampleForPolling: (
        logFile: string,
        id: number | string,
        epoch: number,
      ) => {
        // Clear the previous sample so component uses runningEvents instead
        // of old sample.events
        selectedSampleRef.current = undefined;
        set((state) => {
          state.sample.selectedSampleObject = undefined;
          state.sample.sampleInState = false;
          state.sample.runningEvents = [];
          // Set the new sample identifier for the sample we're about to poll
          state.sample.sample_identifier = {
            id,
            epoch,
            logFile,
          };
        });
      },
      setSampleIdentifier: (
        logFile: string,
        id: number | string,
        epoch: number,
      ) => {
        set((state) => {
          state.sample.sample_identifier = { id, epoch, logFile };
        });
      },
      setRunningEvents: (events: Event[]) => {
        set((state) => {
          state.sample.runningEvents = events;
        });
      },
    },
  } as const;

  const cleanup = () => {
    cleanupSamplePolling();
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
