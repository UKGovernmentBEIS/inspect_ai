// src/store/index.ts
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { immer } from "zustand/middleware/immer";
import { Capabilities, ClientAPI } from "../api/types";
import { AppSlice, createAppSlice, initializeAppSlice } from "./appSlice";
import { createLogSlice, initalialLogSlice, LogSlice } from "./logSlice";
import { createLogsSlice, initializeLogsSlice, LogsSlice } from "./logsSlice";

export interface StoreState extends AppSlice, LogsSlice, LogSlice {
  // Shared data
  api: ClientAPI | null;

  // Global actions
  initialize: (api: ClientAPI, capabilities: Capabilities) => void;
}

export const useStore = create<StoreState>()(
  persist(
    immer((set, get, store) => ({
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
        initalialLogSlice(set);
      },

      // Create the slices and merge them in
      ...createAppSlice(set, get, store),
      ...createLogsSlice(set, get, store),
      ...createLogSlice(set, get, store),
    })),
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
