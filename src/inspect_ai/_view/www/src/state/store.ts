// src/store/index.ts
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { immer } from "zustand/middleware/immer";
import { Capabilities, ClientAPI } from "../api/types";
import {
  AppSlice,
  createAppSlice,
  initializeAppSlice,
  selectAppActions,
  selectAppCapabilities,
  selectAppState,
} from "./appSlice";

// Define the complete store state
interface StoreState extends AppSlice {
  // Shared data
  api: ClientAPI | null;

  // Global actions
  initialize: (api: ClientAPI, capabilities: Capabilities) => void;
}

// Create the combined store with immer middleware
export const useStore = create<StoreState>()(
  persist(
    immer((set, get, store) => ({
      // Shared state
      api: null,

      // Initialize function
      initialize: (api, capabilities) => {
        set((state) => {
          state.api = api;
        });

        // Initialize application slices
        initializeAppSlice(set, capabilities);
      },

      // Create the slices and merge them in
      ...createAppSlice(set, get, store),
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

// Convenience hooks for components
export const useAppState = () => useStore(selectAppState);
export const useAppActions = () => useStore(selectAppActions);
export const useAppCapabilities = () => useStore(selectAppCapabilities);

// Combined hook that includes both state and actions
export const useAppStore = () => {
  const state = useAppState();
  const actions = useAppActions();
  const capabilities = useAppCapabilities();

  return {
    ...state,
    ...actions,
    capabilities,
  };
};

// Initialize the store
export const initializeStore = (api: ClientAPI, capabilities: Capabilities) => {
  useStore.getState().initialize(api, capabilities);
};
