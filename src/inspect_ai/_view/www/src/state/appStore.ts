// src/stores/appStore.ts
import { create } from "zustand";
import { immer } from "zustand/middleware/immer";
import { Capabilities } from "../api/types";
import { AppState, AppStatus } from "../types";
import { clearDocumentSelection } from "../utils/browser";

interface AppStore extends AppState {
  // Actions
  setStatus: (status: AppStatus) => void;
  setOffcanvas: (show: boolean) => void;
  setShowFind: (show: boolean) => void;
  hideFind: () => void;

  // Additional
  capabilities: Capabilities;
  getState: () => { app: AppState };
}

// Initial state
const initialState: AppState = {
  status: { loading: false },
  offcanvas: false,
  showFind: false,
};

export const useAppStore = create<AppStore>()(
  immer((set, get) => ({
    ...initialState,
    capabilities: {} as Capabilities,

    // Actions
    setStatus: (status) =>
      set((state) => {
        state.status = status;
      }),
    setOffcanvas: (show) =>
      set((state) => {
        state.offcanvas = show;
      }),
    setShowFind: (show) =>
      set((state) => {
        state.showFind = show;
      }),
    hideFind: () => {
      clearDocumentSelection();
      set((state) => {
        state.showFind = false;
      });
    },

    getState: () => ({
      app: {
        status: get().status,
        offcanvas: get().offcanvas,
        showFind: get().showFind,
      },
    }),
  })),
);

// Initialize capabilities
export const initializeAppStore = (
  capabilities: Capabilities,
  initialState?: Partial<AppState>,
) => {
  useAppStore.setState((state) => {
    state.capabilities = capabilities;
    if (initialState) {
      state.status = initialState.status || state.status;
      state.offcanvas =
        initialState.offcanvas !== undefined
          ? initialState.offcanvas
          : state.offcanvas;
      state.showFind =
        initialState.showFind !== undefined
          ? initialState.showFind
          : state.showFind;
    }
  });
};
