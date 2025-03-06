import { create, StoreApi, UseBoundStore } from "zustand";
import { devtools, persist } from "zustand/middleware";
import { immer } from "zustand/middleware/immer";
import { Capabilities, ClientAPI, ClientStorage } from "../api/types";
import { createLogger } from "../utils/logger";
import { AppSlice, createAppSlice, initializeAppSlice } from "./appSlice";
import { createLogSlice, initalializeLogSlice, LogSlice } from "./logSlice";
import { createLogsSlice, initializeLogsSlice, LogsSlice } from "./logsSlice";
import {
  createSampleSlice,
  initializeSampleSlice,
  SampleSlice,
} from "./sampleSlice";

const log = createLogger("store");

export interface StoreState extends AppSlice, LogsSlice, LogSlice, SampleSlice {
  // The shared api
  api?: ClientAPI | null;

  // Global actions
  initialize: (api: ClientAPI, capabilities: Capabilities) => void;
  cleanup: () => void;
}

// The data that will actually be persisted
export type PersistedState = {
  app: AppSlice["app"];
  log: LogSlice["log"];
  logs: LogsSlice["logs"];
  sample: SampleSlice["sample"];
};

// The store implementation (this will be set when the store is initialized)
let storeImplementation: UseBoundStore<StoreApi<StoreState>> | null = null;

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
  // Create the storage implementation
  const storageImplementation = {
    getItem: <T>(name: string): T | null => {
      return storage ? (storage.getItem(name) as T) : null;
    },
    setItem: <T>(name: string, value: T): void => {
      if (storage) {
        storage.setItem(name, value);
      }
    },
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
          const [appSlice, appCleanup] = createAppSlice(set, get, store);
          const [logsSlice, logsCleanup] = createLogsSlice(set, get, store);
          const [logSlice, logCleanup] = createLogSlice(set, get, store);
          const [sampleSlice, sampleCleanup] = createSampleSlice(
            set,
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
          storage: storageImplementation,
          partialize: (state) => {
            const persisted: PersistedState = {
              app: state.app,
              log: state.log,
              logs: state.logs,
              sample: state.sample,
            };
            return persisted as unknown as StoreState;
          },
          version: 1,
          onRehydrateStorage: (state: StoreState) => {
            return (hydrationState, error) => {
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
  storeImplementation = store;
  store.getState().initialize(api, capabilities);
};
