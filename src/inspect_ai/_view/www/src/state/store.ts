// src/store/index.ts
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { immer } from "zustand/middleware/immer";
import { Capabilities, ClientAPI } from "../api/types";
import { AppSlice, createAppSlice, initializeAppSlice } from "./appSlice";
import { createLogSlice, initalializeLogSlice, LogSlice } from "./logSlice";
import { createLogsSlice, initializeLogsSlice, LogsSlice } from "./logsSlice";
import {
  createSampleSlice,
  initializeSampleSlice,
  SampleSlice,
} from "./sampleSlice";

export interface StoreState extends AppSlice, LogsSlice, LogSlice, SampleSlice {
  // Shared data
  api: ClientAPI | null;

  // Global actions
  initialize: (api: ClientAPI, capabilities: Capabilities) => void;

  cleanup: () => void;
}

export const useStore = create<StoreState>()(
  persist(
    immer((set, get, store) => {
      const [appSlice, appCleanup] = createAppSlice(set, get, store);
      const [logsSlice, logsCleanup] = createLogsSlice(set, get, store);
      const [logSlice, logCleanup] = createLogSlice(set, get, store);
      const [sampleSlice, sampleCleanup] = createSampleSlice(set, get, store);

      return {
        // Shared state
        api: null,

        // Initialize
        initialize: (api, capabilities) => {
          set((state) => {
            state.api = api;
          });

          // Initialize application slices
          initializeAppSlice(set, capabilities);
          initializeLogsSlice(set);
          initalializeLogSlice(set);
          initializeSampleSlice(set);
        },

        // Create the slices and merge them in
        ...appSlice,
        ...logsSlice,
        ...logSlice,
        ...sampleSlice,

        cleanup: () => {
          appCleanup();
          logsCleanup();
          logCleanup();
          sampleCleanup();
        },
      };
    }),
    {
      name: "app-storage",
      partialize: (state) => ({
        // TODO: Partialize state
        // Thing out state to only store the parts that
        // should be stored
        app: {
          offcanvas: state.app.offcanvas,
          showFind: state.app.showFind,
          // Don't persist status
        },
        logs: {},
        log: {},
      }),
    },
  ),
);

// Initialize the store
export const initializeStore = (api: ClientAPI, capabilities: Capabilities) => {
  useStore.getState().initialize(api, capabilities);
};
