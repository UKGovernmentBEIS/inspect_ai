import { create } from "zustand";
import { ClientAPI, EvalLogHeader, LogFiles } from "../api/types";
import { LogsState } from "../types";
import { createLogger } from "../utils/logger";
import { sleep } from "../utils/sync";
import { useStore } from "./store";

interface LogsStore extends LogsState {
  // API reference
  api: ClientAPI | null;

  // Actions
  setLogs: (logs: LogFiles) => void;
  setLogHeaders: (headers: Record<string, EvalLogHeader>) => void;
  setHeadersLoading: (loading: boolean) => void;
  setSelectedLogIndex: (index: number) => void;
  setSelectedLogFile: (logUrl: string) => void;
  updateLogHeaders: (headers: Record<string, EvalLogHeader>) => void;

  // Functions that use the internal API reference
  refreshLogs: () => Promise<void>;
  selectLogFile: (logUrl: string) => Promise<void>;
  loadHeaders: () => Promise<void>;
  loadLogs: () => Promise<LogFiles>;

  // Method to get selected log file
  getSelectedLogFile: () => string | undefined;

  // For compatibility
  getState: () => { logs: LogsState };
}

// Initial state
const initialState: LogsState = {
  logs: { log_dir: "", files: [] },
  logHeaders: {},
  headersLoading: false,
  selectedLogIndex: -1,
};

const log = createLogger("LogsStore");

export const useLogsStore = create<LogsStore>()((set, get) => ({
  ...initialState,
  api: null,

  // Actions
  setLogs: (logs) => {
    set({ logs });

    // If we have files in the logs, load the headers
    if (logs.files.length > 0) {
      // Use setTimeout to ensure state is updated first
      setTimeout(() => {
        const state = useLogsStore.getState();
        if (!state.headersLoading) {
          state.loadHeaders();
        }
      }, 100);
    }
  },
  setLogHeaders: (logHeaders) => set({ logHeaders }),
  setHeadersLoading: (headersLoading) => set({ headersLoading }),
  setSelectedLogIndex: (selectedLogIndex) => set({ selectedLogIndex }),

  setSelectedLogFile: (logUrl) => {
    const state = get();
    const index = state.logs.files.findIndex((val) =>
      logUrl.endsWith(val.name),
    );

    if (index > -1) {
      set({ selectedLogIndex: index });
    }
  },

  updateLogHeaders: (headers) =>
    set((state) => ({
      logHeaders: { ...state.logHeaders, ...headers },
    })),

  // Helper function to load logs
  loadLogs: async () => {
    const api = get().api;
    if (!api) {
      console.error("API not initialized in LogsStore");
      return { log_dir: "", files: [] };
    }

    try {
      log.debug("LOADING LOG FILES");
      return await api.get_log_paths();
    } catch (e) {
      console.log(e);
      useStore
        .getState()
        .appActions.setStatus({ loading: false, error: e as Error });
      return { log_dir: "", files: [] };
    }
  },

  // Refresh logs
  refreshLogs: async () => {
    log.debug("REFRESH LOGS");
    const state = get();
    const refreshedLogs = await get().loadLogs();

    // Set the logs first
    set({ logs: refreshedLogs || { log_dir: "", files: [] } });

    // Preserve the selected log even if new logs appear
    const currentLog =
      refreshedLogs.files[
        state.selectedLogIndex > -1 ? state.selectedLogIndex : 0
      ];

    if (currentLog) {
      const newIndex = refreshedLogs?.files.findIndex((file) =>
        currentLog.name.endsWith(file.name),
      );

      if (newIndex !== undefined && newIndex !== -1) {
        set({ selectedLogIndex: newIndex });
      }
    }

    // Always load headers if we have files, regardless of how logs were refreshed
    if (refreshedLogs.files.length > 0) {
      setTimeout(() => {
        const currentState = useLogsStore.getState();
        if (!currentState.headersLoading) {
          currentState.loadHeaders();
        }
      }, 100);
    }
  },

  // Select a specific log file
  selectLogFile: async (logUrl) => {
    const state = get();
    const index = state.logs.files.findIndex((val) =>
      val.name.endsWith(logUrl),
    );

    // It is already loaded
    if (index > -1) {
      set({ selectedLogIndex: index });
    } else {
      // It isn't yet loaded, so refresh the logs and try to load it from there
      const result = await get().loadLogs();
      const idx = result?.files.findIndex((file) => logUrl.endsWith(file.name));

      set({
        logs: result || { log_dir: "", files: [] },
        selectedLogIndex: idx !== undefined && idx > -1 ? idx : 0,
      });
    }
  },

  // Load headers
  loadHeaders: async () => {
    const state = get();
    const api = get().api;

    if (!api) {
      console.error("API not initialized in LogsStore");
      return;
    }

    log.debug("LOADING HEADERS");
    set({ headersLoading: true });

    // Group into chunks
    const chunkSize = 8;
    const fileLists = [];
    for (let i = 0; i < state.logs.files.length; i += chunkSize) {
      const chunk = state.logs.files
        .slice(i, i + chunkSize)
        .map((logFile) => logFile.name);
      fileLists.push(chunk);
    }

    // Chunk by chunk, read the header information
    try {
      let counter = 0;
      for (const fileList of fileLists) {
        counter++;
        log.debug(`LOADING ${counter} of ${fileLists.length} CHUNKS`);
        const headers = await api.get_log_headers(fileList);
        const updatedHeaders: Record<string, EvalLogHeader> = {};

        headers.forEach((header, index) => {
          const logFile = fileList[index];
          updatedHeaders[logFile] = header as EvalLogHeader;
        });

        set({
          ...get(),
          logHeaders: { ...get().logHeaders, ...updatedHeaders },
        });

        if (headers.length === chunkSize) {
          await sleep(5000);
        }
      }
    } catch (e: unknown) {
      if (
        e instanceof Error &&
        (e.message === "Load failed" || e.message === "Failed to fetch")
      ) {
        // This happens if the server disappears
        useStore.getState().appActions.setStatus({ loading: false });
      } else {
        console.log(e);
        useStore
          .getState()
          .appActions.setStatus({ loading: false, error: e as Error });
      }
    }

    set({ headersLoading: false });
  },

  // Method to get selected log file
  getSelectedLogFile: () => {
    const state = get();
    const file = state.logs.files[state.selectedLogIndex];
    return file !== undefined ? file.name : undefined;
  },

  // For compatibility with existing code
  getState: () => ({ logs: get() }),
}));

// The selected log file
export const useSelectedLogFile = () =>
  useLogsStore((state) => {
    const files = state.logs.files;
    const selectedIndex = state.selectedLogIndex;

    const file = files[selectedIndex];
    return file !== undefined ? file.name : undefined;
  });

// Initialize store with API and optional initial state
export const initializeLogsStore = (
  api: ClientAPI,
  initialState?: Partial<LogsState>,
) => {
  useLogsStore.setState((state) => ({
    ...state,
    api,
    ...(initialState || {}),
  }));
};
