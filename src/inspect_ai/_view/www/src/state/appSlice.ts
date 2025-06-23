import { StateSnapshot } from "react-virtuoso";
import { AppState, AppStatus } from "../app/types";
import { Capabilities } from "../client/api/types";
import { kLogViewSamplesTabId, kSampleTranscriptTabId } from "../constants";
import { clearDocumentSelection } from "../utils/browser";
import { StoreState } from "./store";

export interface AppSlice {
  app: AppState;
  capabilities: Capabilities;
  appActions: {
    setStatus: (status: AppStatus) => void;
    setShowFind: (show: boolean) => void;
    hideFind: () => void;

    setShowingSampleDialog: (showing: boolean) => void;
    setWorkspaceTab: (tab: string) => void;
    clearWorkspaceTab: () => void;

    setInitialState: (
      log: string,
      sample_id?: string,
      sample_epoch?: string,
    ) => void;
    clearInitialState: () => void;

    setSampleTab: (tab: string) => void;
    clearSampleTab: () => void;

    getScrollPosition: (name: string) => number | undefined;
    setScrollPosition: (name: string, value: number) => void;

    getListPosition: (name: string) => StateSnapshot | undefined;
    setListPosition: (name: string, state: StateSnapshot) => void;
    clearListPosition: (name: string) => void;

    getCollapsed: (name: string, defaultValue?: boolean) => boolean;
    setCollapsed: (name: string, value: boolean) => void;

    getMessageVisible: (name: string, defaultValue?: boolean) => boolean;
    setMessageVisible: (name: string, value: boolean) => void;
    clearMessageVisible: (name: string) => void;

    getPropertyValue: <T>(bagName: string, key: string, defaultValue?: T) => T;
    setPropertyValue: <T>(bagName: string, key: string, value: T) => void;
    removePropertyValue: (bagName: string, key: string) => void;

    setPagination: (
      name: string,
      pagination: { page: number; pageSize: number },
    ) => void;
    clearPagination: (name: string) => void;

    setUrlHash: (urlHash: string) => void;

    setSingleFileMode: (singleFile: boolean) => void;
  };
}

const kDefaultWorkspaceTab = kLogViewSamplesTabId;
const kDefaultSampleTab = kSampleTranscriptTabId;

const initialState: AppState = {
  status: { loading: false },
  showFind: false,
  dialogs: {
    sample: false,
  },
  tabs: {
    workspace: kDefaultWorkspaceTab,
    sample: kDefaultSampleTab,
  },
  scrollPositions: {},
  listPositions: {},
  collapsed: {},
  messages: {},
  propertyBags: {},
  pagination: {},
};

export const createAppSlice = (
  set: (fn: (state: StoreState) => void) => void,
  get: () => StoreState,
  _store: any,
): [AppSlice, () => void] => {
  const getBoolRecord = (
    record: Record<string, boolean>,
    name: string,
    defaultValue?: boolean,
  ) => {
    if (Object.keys(record).includes(name)) {
      return record[name];
    } else {
      return defaultValue || false;
    }
  };

  const slice = {
    // State
    app: initialState,
    capabilities: {} as Capabilities,

    // Actions
    appActions: {
      setStatus: (status: AppStatus) =>
        set((state) => {
          state.app.status = status;
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
      setShowingSampleDialog: (showing: boolean) => {
        const state = get();
        const isShowing = state.app.dialogs.sample;

        if (showing === isShowing) {
          return;
        }

        set((state) => {
          state.app.dialogs.sample = showing;
        });
        if (!showing) {
          const state = get();
          state.appActions.clearSampleTab();
        }
      },
      setWorkspaceTab: (tab: string) => {
        set((state) => {
          state.app.tabs.workspace = tab;
        });
      },
      clearWorkspaceTab: () => {
        set((state) => {
          state.app.tabs.workspace = kDefaultWorkspaceTab;
        });
      },
      setInitialState: (
        log: string,
        sample_id?: string,
        sample_epoch?: string,
      ) => {
        set((state) => {
          state.app.initialState = {
            log,
            sample_id,
            sample_epoch,
          };
        });
      },
      clearInitialState: () => {
        set((state) => {
          state.app.initialState = undefined;
        });
      },
      setSampleTab: (tab: string) => {
        set((state) => {
          state.app.tabs.sample = tab;
        });
      },
      clearSampleTab: () => {
        set((state) => {
          state.app.tabs.sample = kDefaultSampleTab;
        });
      },
      getScrollPosition: (name: string) => {
        const state = get();
        return state.app.scrollPositions[name];
      },
      setScrollPosition: (name: string, position: number) => {
        set((state) => {
          state.app.scrollPositions[name] = position;
        });
      },
      getListPosition: (name: string) => {
        const state = get();
        if (Object.keys(state.app.listPositions).includes(name)) {
          return state.app.listPositions[name];
        } else {
          return undefined;
        }
      },
      setListPosition: (name: string, position: StateSnapshot) => {
        set((state) => {
          state.app.listPositions[name] = position;
        });
      },
      clearListPosition: (name: string) => {
        set((state) => {
          // Remove the key
          const newListPositions = { ...state.app.listPositions };
          delete newListPositions[name];

          return {
            app: {
              ...state.app,
              listPositions: newListPositions,
            },
          };
        });
      },
      getCollapsed: (name: string, defaultValue?: boolean) => {
        return getBoolRecord(get().app.collapsed, name, defaultValue);
      },
      setCollapsed: (name: string, value: boolean) => {
        set((state) => {
          state.app.collapsed[name] = value;
        });
      },
      getMessageVisible: (name: string, defaultValue?: boolean) => {
        return getBoolRecord(get().app.messages, name, defaultValue);
      },
      setMessageVisible: (name: string, value: boolean) => {
        set((state) => {
          state.app.messages[name] = value;
        });
      },
      clearMessageVisible: (name: string) => {
        set((state) => {
          delete state.app.messages[name];
        });
      },
      getPropertyValue: <T>(
        bagName: string,
        key: string,
        defaultValue?: T,
      ): T => {
        const state = get();
        const bag = state.app.propertyBags[bagName] || {};
        return (key in bag ? bag[key] : defaultValue) as T;
      },

      setPropertyValue: <T>(bagName: string, key: string, value: T) => {
        set((state) => {
          // Create the bag if it doesn't exist
          if (!state.app.propertyBags[bagName]) {
            state.app.propertyBags[bagName] = {};
          }
          // Only update the specific key
          state.app.propertyBags[bagName][key] = value;
        });
      },

      removePropertyValue: (bagName: string, key: string) => {
        set((state) => {
          if (state.app.propertyBags[bagName]) {
            const { [key]: _, ...rest } = state.app.propertyBags[bagName];
            state.app.propertyBags[bagName] = rest;
          }
        });
      },

      setUrlHash: (urlHash: string) => {
        set((state) => {
          state.app.urlHash = urlHash;
        });
      },
      setSingleFileMode: (singleFile: boolean) => {
        set((state) => {
          state.app.singleFileMode = singleFile;
        });
      },
      setPagination: (
        name: string,
        pagination: { page: number; pageSize: number },
      ) => {
        set((state) => {
          state.app.pagination[name] = pagination;
        });
      },
      clearPagination: (name: string) => {
        set((state) => {
          delete state.app.pagination[name];
        });
      },
    },
  } as const;

  const cleanup = () => {};

  return [slice, cleanup];
};

export const initializeAppSlice = (
  set: (fn: (state: StoreState) => void) => void,
  capabilities: Capabilities,
) => {
  set((state) => {
    state.capabilities = capabilities;
    if (!state.app) {
      state.app = initialState;
    }
  });
};
