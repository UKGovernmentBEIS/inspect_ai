import { EvalLogHeader, LogFiles } from "../api/types";
import { LogsState } from "../types";
import { createLogger } from "../utils/logger";
import { createLogsPolling } from "./logsPolling";
import { StoreState } from "./store";

const log = createLogger("Log Slice");

export interface LogsSlice {
  logs: LogsState;
  logsActions: {
    // Update State
    setLogs: (logs: LogFiles) => void;
    setLogHeaders: (headers: Record<string, EvalLogHeader>) => void;
    setHeadersLoading: (loading: boolean) => void;
    setSelectedLogIndex: (index: number) => void;
    setSelectedLogFile: (logUrl: string) => void;
    updateLogHeaders: (headers: Record<string, EvalLogHeader>) => void;

    // Fetch or update logs
    refreshLogs: () => Promise<void>;
    selectLogFile: (logUrl: string) => Promise<void>;
    loadLogs: () => Promise<LogFiles>;

    // Computed values
    getSelectedLogFile: () => string | undefined;
  };
}

const initialState: LogsState = {
  logs: { log_dir: "", files: [] },
  logHeaders: {},
  headersLoading: false,
  selectedLogIndex: -1,
};

export const createLogsSlice = (
  set: (fn: (state: StoreState) => void) => void,
  get: () => StoreState,
  _store: any,
): [LogsSlice, () => void] => {
  const logsPolling = createLogsPolling(get, set);

  const slice = {
    // State
    logs: initialState,

    // Actions
    logsActions: {
      setLogs: (logs: LogFiles) => {
        set((state) => {
          state.logs.logs = logs;
        });

        // If we have files in the logs, load the headers
        if (logs.files.length > 0) {
          // ensure state is updated first
          setTimeout(() => {
            const currentState = get();
            if (!currentState.logs.headersLoading) {
              logsPolling.startPolling(logs);
            }
          }, 100);
        }
      },
      setLogHeaders: (headers: Record<string, EvalLogHeader>) =>
        set((state) => {
          state.logs.logHeaders = headers;
        }),
      setHeadersLoading: (loading: boolean) =>
        set((state) => {
          state.logs.headersLoading = loading;
        }),
      setSelectedLogIndex: (selectedLogIndex: number) => {
        set((state) => {
          state.logs.selectedLogIndex = selectedLogIndex;
        });
      },
      updateLogHeaders: (headers: Record<string, EvalLogHeader>) =>
        set((state) => {
          state.logs.logHeaders = { ...get().logs.logHeaders, ...headers };
        }),

      setSelectedLogFile: (logUrl: string) => {
        const state = get();
        const index = state.logs.logs.files.findIndex((val) =>
          logUrl.endsWith(val.name),
        );

        if (index > -1) {
          state.logsActions.setSelectedLogIndex(index);
        }
      },

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
          get().appActions.setStatus({ loading: false, error: e as Error });
          return { log_dir: "", files: [] };
        }
      },
      refreshLogs: async () => {
        log.debug("REFRESH LOGS");
        const state = get();
        const refreshedLogs = await state.logsActions.loadLogs();

        // Set the logs first
        state.logsActions.setLogs(refreshedLogs || { log_dir: "", files: [] });

        // Preserve the selected log even if new logs appear
        const currentLog =
          refreshedLogs.files[
            state.logs.selectedLogIndex > -1 ? state.logs.selectedLogIndex : 0
          ];

        if (currentLog) {
          const newIndex = refreshedLogs?.files.findIndex((file) =>
            currentLog.name.endsWith(file.name),
          );

          if (newIndex !== undefined && newIndex !== -1) {
            state.logsActions.setSelectedLogIndex(newIndex);
          }
        }
      },
      // Select a specific log file
      selectLogFile: async (logUrl: string) => {
        const state = get();
        const index = state.logs.logs.files.findIndex((val) =>
          val.name.endsWith(logUrl),
        );

        // It is already loaded
        if (index > -1) {
          state.logsActions.setSelectedLogIndex(index);
        } else {
          // It isn't yet loaded, so refresh the logs and try to load it from there
          const result = await state.logsActions.loadLogs();
          const idx = result?.files.findIndex((file) =>
            logUrl.endsWith(file.name),
          );

          state.logsActions.setLogs(result || { log_dir: "", files: [] });
          state.logsActions.setSelectedLogIndex(
            idx !== undefined && idx > -1 ? idx : 0,
          );
        }
      },

      getSelectedLogFile: () => {
        const state = get();
        const file = state.logs.logs.files[state.logs.selectedLogIndex];
        return file !== undefined ? file.name : undefined;
      },
    },
  } as const;

  const cleanup = () => {};

  return [slice, cleanup];
};

export const initializeLogsSlice = <T extends LogsSlice>(
  set: (fn: (state: T) => void) => void,
) => {
  set((state) => {
    if (!state.logs) {
      state.logs = initialState;
    }
  });
};
