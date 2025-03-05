import { Capabilities } from "../api/types";
import { AppState, AppStatus } from "../types";
import { clearDocumentSelection } from "../utils/browser";
import { StoreState } from "./store";

export interface AppSlice {
  app: AppState;
  capabilities: Capabilities;
  appActions: {
    setStatus: (status: AppStatus) => void;
    setOffcanvas: (show: boolean) => void;
    setShowFind: (show: boolean) => void;
    hideFind: () => void;
  };
}

const initialState: AppState = {
  status: { loading: false },
  offcanvas: false,
  showFind: false,
};

export const createAppSlice = (
  set: (fn: (state: StoreState) => void) => void,
  _get: () => StoreState,
  _store: any,
) => {
  return {
    // State
    app: initialState,
    capabilities: {} as Capabilities,

    // Actions
    appActions: {
      setStatus: (status: AppStatus) =>
        set((state) => {
          state.app.status = status;
        }),

      setOffcanvas: (show: boolean) =>
        set((state) => {
          state.app.offcanvas = show;
        }),

      setShowFind: (show: boolean) =>
        set((state) => {
          state.app.showFind = show;
        }),

      hideFind: () => {
        clearDocumentSelection();
        set((state) => {
          state.app.showFind = false;
        });
      },
    },
  } as const;
};

export const initializeAppSlice = (
  set: (fn: (state: StoreState) => void) => void,
  capabilities: Capabilities,
  restoreState?: Partial<AppState>,
) => {
  set((state) => {
    state.capabilities = capabilities;
    state.app = { ...initialState };
    if (restoreState) {
      if (restoreState.status) {
        state.app.status = restoreState.status;
      }

      if (restoreState.offcanvas !== undefined) {
        state.app.offcanvas = restoreState.offcanvas;
      }

      if (restoreState.showFind !== undefined) {
        state.app.showFind = restoreState.showFind;
      }
    }
  });
};
