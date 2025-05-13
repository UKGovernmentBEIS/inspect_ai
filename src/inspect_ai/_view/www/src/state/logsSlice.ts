import { LogsState } from "../app/types";
import { EvalLogHeader, LogFiles } from "../client/api/types";
import { createLogger } from "../utils/logger";
import { createLogsPolling } from "./logsPolling";
import { StoreState } from "./store";

const log = createLogger("Log Slice");

const kEmptyLogs: LogFiles = {
  log_dir: "",
  files: [],
};

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
  };
}

const initialState: LogsState = {
  logs: kEmptyLogs,
  logHeaders: {},
  headersLoading: false,
  selectedLogIndex: -1,
  selectedLogFile: undefined as string | undefined,
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
          state.logs.selectedLogFile =
            state.logs.selectedLogIndex > -1
              ? logs.files[state.logs.selectedLogIndex]?.name
              : undefined;
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
          const file = state.logs.logs.files[selectedLogIndex];
          state.logs.selectedLogFile = file ? file.name : undefined;
        });
      },
      updateLogHeaders: (headers: Record<string, EvalLogHeader>) =>
        set((state) => {
          state.logs.logHeaders = { ...get().logs.logHeaders, ...headers };
        }),

      setSelectedLogFile: (logUrl: string) => {
        const state = get();
        const index = state.logs.logs.files.findIndex((val: { name: string }) =>
          logUrl.endsWith(val.name),
        );

        if (index > -1) {
          state.logsActions.setSelectedLogIndex(index);
          state.logs.selectedLogFile =
            state.logs.logs.files[index]?.name ?? undefined;
        }
      },

      // Helper function to load logs
      loadLogs: async () => {
        const api = get().api;
        if (!api) {
          console.error("API not initialized in LogsStore");
          return kEmptyLogs;
        }

        try {
          log.debug("LOADING LOG FILES");
          return await api.get_log_paths();
        } catch (e) {
          console.log(e);
          get().appActions.setStatus({ loading: false, error: e as Error });
          return kEmptyLogs;
        }
      },
      refreshLogs: async () => {
        log.debug("REFRESH LOGS");
        const state = get();
        const refreshedLogs = await state.logsActions.loadLogs();

        // Preserve the selected log even if new logs appear
        const currentLog =
          state.logs.logs.files[
            state.logs.selectedLogIndex > -1 ? state.logs.selectedLogIndex : 0
          ];

        // Set the logs first
        state.logsActions.setLogs(refreshedLogs || kEmptyLogs);

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
        const index = state.logs.logs.files.findIndex((val: { name: string }) =>
          val.name.endsWith(logUrl),
        );

        // It is already loaded
        if (index > -1) {
          state.logsActions.setSelectedLogIndex(index);
        } else {
          // It isn't yet loaded, so refresh the logs and try to load it from there
          const result = await state.logsActions.loadLogs();
          const idx = result?.files.findIndex((file) =>
            file.name.endsWith(logUrl),
          );

          state.logsActions.setLogs(result || kEmptyLogs);
          state.logsActions.setSelectedLogIndex(
            idx !== undefined && idx > -1 ? idx : 0,
          );
        }
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
