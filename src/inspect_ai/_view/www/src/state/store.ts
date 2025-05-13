import { enableMapSet } from "immer";
import { create, StoreApi, UseBoundStore } from "zustand";
import { devtools, persist } from "zustand/middleware";
import { immer } from "zustand/middleware/immer";
import { Capabilities, ClientAPI, ClientStorage } from "../client/api/types";
import { createLogger } from "../utils/logger";
import { debounce } from "../utils/sync";
import { AppSlice, createAppSlice, initializeAppSlice } from "./appSlice";
import { createLogSlice, initalializeLogSlice, LogSlice } from "./logSlice";
import { createLogsSlice, initializeLogsSlice, LogsSlice } from "./logsSlice";
import {
  createSampleSlice,
  handleRehydrate,
  initializeSampleSlice,
  SampleSlice,
} from "./sampleSlice";
import { filterState } from "./store_filter";

const log = createLogger("store");

export interface StoreState extends AppSlice, LogsSlice, LogSlice, SampleSlice {
  // The shared api
  api?: ClientAPI | null;

  // Global actions
  initialize: (api: ClientAPI, capabilities: Capabilities) => void;
  cleanup: () => void;
}

export let storeImplementation: UseBoundStore<StoreApi<StoreState>> | null =
  null;

// The data that will actually be persisted
export type PersistedState = {
  app: AppSlice["app"];
  log: LogSlice["log"];
  logs: LogsSlice["logs"];
  sample: SampleSlice["sample"];
};

// Create a proxy store that forwards calls to the real store once initialized
export const useStore = ((selector?: any) => {
  if (!storeImplementation) {
    throw new Error(
      "Store accessed before initialization. Call initializeStore first.",
    );
  }
  return selector ? storeImplementation(selector) : storeImplementation();
}) as UseBoundStore<StoreApi<StoreState>>;

// Initialize the store
export const initializeStore = (
  api: ClientAPI,
  capabilities: Capabilities,
  storage?: ClientStorage,
) => {
  enableMapSet();

  // Create the storage implementation
  const storageImplementation = {
    getItem: <T>(name: string): T | null => {
      return storage ? (storage.getItem(name) as T) : null;
    },
    setItem: debounce(<T>(name: string, value: T): void => {
      if (storage) {
        storage.setItem(name, value);
      }
    }, 1000),
    removeItem: (name: string): void => {
      if (storage) {
        storage.removeItem(name);
      }
    },
  };

  // Create the actual store
  const store = create<StoreState>()(
    devtools(
      persist(
        immer((set, get, store) => {
          const [appSlice, appCleanup] = createAppSlice(
            set as (fn: (state: StoreState) => void) => void,
            get,
            store,
          );
          const [logsSlice, logsCleanup] = createLogsSlice(
            set as (fn: (state: StoreState) => void) => void,
            get,
            store,
          );
          const [logSlice, logCleanup] = createLogSlice(
            set as (fn: (state: StoreState) => void) => void,
            get,
            store,
          );
          const [sampleSlice, sampleCleanup] = createSampleSlice(
            set as (fn: (state: StoreState) => void) => void,
            get,
            store,
          );

          return {
            // Shared state
            api: null,

            // Initialize
            initialize: (api, capabilities) => {
              set((state) => {
                state.api = api;
              });

              // Initialize application slices
              initializeAppSlice(
                set as (fn: (state: StoreState) => void) => void,
                capabilities,
              );
              initializeLogsSlice(
                set as (fn: (state: StoreState) => void) => void,
              );
              initalializeLogSlice(
                set as (fn: (state: StoreState) => void) => void,
              );
              initializeSampleSlice(
                set as (fn: (state: StoreState) => void) => void,
              );
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
          storage: storageImplementation,
          partialize: (state) => {
            const persisted: PersistedState = filterState({
              app: { ...state.app, rehydrated: true },
              log: state.log,
              logs: state.logs,
              sample: state.sample,
            });
            log.debug("PARTIALIZED STATE", persisted);
            return persisted as unknown as StoreState;
          },
          version: 1,
          onRehydrateStorage: (state: StoreState) => {
            return (hydrationState, error) => {
              handleRehydrate(state);
              log.debug("REHYDRATING STATE");
              if (error) {
                log.debug("ERROR", { error });
              } else {
                log.debug("STATE", { state, hydrationState });
              }
            };
          },
        },
      ),
    ),
  );

  // Set the implementation and initialize it
  storeImplementation = store as UseBoundStore<StoreApi<StoreState>>;
  store.getState().initialize(api, capabilities);
};
