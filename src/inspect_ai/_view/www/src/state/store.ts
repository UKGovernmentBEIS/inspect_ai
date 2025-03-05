// src/store/index.ts
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { immer } from "zustand/middleware/immer";
import { Capabilities, ClientAPI } from "../api/types";
import { AppSlice, createAppSlice, initializeAppSlice } from "./appSlice";
import { createLogsSlice, initializeLogsSlice, LogsSlice } from "./logsSlice";

// Define the complete store state
export interface StoreState extends AppSlice, LogsSlice {
  // Shared data
  api: ClientAPI | null;

  // Global state
  globalError: Error | null;
  globalLoading: boolean;

  // Global actions
  initialize: (api: ClientAPI, capabilities: Capabilities) => void;

  setGlobalError: (error: Error | null) => void;
  setGlobalLoading: (loading: boolean) => void;
}

// Create the combined store with immer middleware
export const useStore = create<StoreState>()(
  persist(
    immer((set, get, store) => ({
      // Shared state
      api: null,
      globalError: null,
      globalLoading: false,

      // Initialize function
      initialize: (api, capabilities) => {
        set((state) => {
          state.api = api;
        });

        // Initialize application slices
        initializeAppSlice(set, capabilities);
        initializeLogsSlice(set);
      },

      setGlobalError: (error) => {
        set((state) => {
          state.globalError = error;
        });
      },

      setGlobalLoading: (loading) => {
        set((state) => {
          state.globalLoading = loading;
        });
      },

      // Create the slices and merge them in
      ...createAppSlice(set, get, store),
      ...createLogsSlice(set, get, store),
    })),
    {
      name: "app-storage",
      partialize: (state) => ({
        // Thing out state to only store the parts that
        // should be stored
        app: {
          offcanvas: state.app.offcanvas,
          showFind: state.app.showFind,
          // Don't persist status
        },
      }),
    },
  ),
);

// Initialize the store
export const initializeStore = (api: ClientAPI, capabilities: Capabilities) => {
  useStore.getState().initialize(api, capabilities);
};
