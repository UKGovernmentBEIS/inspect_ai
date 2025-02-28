import {
  createContext,
  Dispatch,
  FC,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
} from "react";
import { ClientAPI, EvalLogHeader, LogFiles } from "../api/types";
import { useAppContext } from "../contexts/AppContext";
import { createLogger } from "../utils/logger";
import { sleep } from "../utils/sync";

// Define action types
type LogsAction =
  | { type: "SET_LOGS"; payload: LogFiles }
  | { type: "SET_LOG_HEADERS"; payload: Record<string, EvalLogHeader> }
  | { type: "SET_HEADERS_LOADING"; payload: boolean }
  | { type: "SET_SELECTED_LOG_INDEX"; payload: number }
  | { type: "SET_SELECTED_LOG_FILE"; payload: string }
  | { type: "UPDATE_LOG_HEADERS"; payload: Record<string, EvalLogHeader> };

// Define the state shape
export interface LogsState {
  logs: LogFiles;
  logHeaders: Record<string, EvalLogHeader>;
  headersLoading: boolean;
  selectedLogIndex: number;
}

// Initial state
const initialLogsState: LogsState = {
  logs: { log_dir: "", files: [] },
  logHeaders: {},
  headersLoading: false,
  selectedLogIndex: -1,
};

// Reducer function
const logsReducer = (state: LogsState, action: LogsAction): LogsState => {
  switch (action.type) {
    case "SET_LOGS":
      return { ...state, logs: action.payload };
    case "SET_LOG_HEADERS":
      return { ...state, logHeaders: action.payload };
    case "SET_HEADERS_LOADING":
      return { ...state, headersLoading: action.payload };
    case "SET_SELECTED_LOG_INDEX":
      return { ...state, selectedLogIndex: action.payload };
    case "SET_SELECTED_LOG_FILE": {
      const index = state.logs.files.findIndex((val) => {
        return action.payload.endsWith(val.name);
      });
      if (index > -1) {
        return { ...state, selectedLogIndex: index };
      } else {
        return state;
      }
    }
    case "UPDATE_LOG_HEADERS":
      return {
        ...state,
        logHeaders: { ...state.logHeaders, ...action.payload },
      };

    default:
      return state;
  }
};

export interface LogsContextType {
  state: LogsState;
  dispatch: Dispatch<LogsAction>;
  refreshLogs: () => Promise<void>;
  selectLogFile: (logUrl: string) => Promise<void>;
  selectedLogFile?: string;
  getState: () => { logs: LogsState };
}

const LogsContext = createContext<LogsContextType | undefined>(undefined);

interface LogsProviderProps {
  initialState?: { logs?: LogsState };
  children: ReactNode;
  api: ClientAPI;
}

export const LogsProvider: FC<LogsProviderProps> = ({
  children,
  initialState,
  api,
}) => {
  const log = useMemo(() => {
    return createLogger("LogsContext");
  }, []);
  const [state, dispatch] = useReducer(
    logsReducer,
    initialState
      ? { ...initialLogsState, ...initialState.logs }
      : initialLogsState,
  );
  const appContext = useAppContext();

  const getState = () => {
    return { logs: state };
  };

  // Load the list of logs
  const loadLogs = async (): Promise<LogFiles> => {
    try {
      log.debug("LOADING LOG FILES");
      const result = await api.get_log_paths();
      return result;
    } catch (e) {
      // Show an error
      console.log(e);
      appContext.dispatch({
        type: "SET_STATUS",
        payload: { loading: false, error: e as Error },
      });
      return { log_dir: "", files: [] };
    }
  };

  const refreshLogs = useCallback(async () => {
    log.debug("REFRESH LOGS");
    const refreshedLogs = await loadLogs();
    dispatch({
      type: "SET_LOGS",
      payload: refreshedLogs || { log_dir: "", files: [] },
    });

    // Preserve the selected log even if new logs appear
    const currentLog =
      refreshedLogs.files[
        state.selectedLogIndex > -1 ? state.selectedLogIndex : 0
      ];

    const newIndex = refreshedLogs?.files.findIndex((file) => {
      return currentLog.name.endsWith(file.name);
    });

    if (newIndex !== undefined) {
      dispatch({
        type: "SET_SELECTED_LOG_INDEX",
        payload: newIndex,
      });
    }
  }, [state.logs, state.selectedLogIndex, dispatch]);

  const selectLogFile = useCallback(
    async (logUrl: string) => {
      const index = state.logs.files.findIndex((val) => {
        return val.name.endsWith(logUrl);
      });

      // It is already loaded
      if (index > -1) {
        dispatch({
          type: "SET_SELECTED_LOG_INDEX",
          payload: index,
        });
      } else {
        // It isn't yet loaded, so refresh the logs
        // and try to load it from there
        const result = await loadLogs();
        const idx = result?.files.findIndex((file) => {
          return logUrl.endsWith(file.name);
        });

        dispatch({
          type: "SET_LOGS",
          payload: result || { log_dir: "", files: [] },
        });
        dispatch({
          type: "SET_SELECTED_LOG_INDEX",
          payload: idx && idx > -1 ? idx : 0,
        });
      }
    },
    [state.logs, dispatch],
  );

  const selectedLogFile = useMemo(() => {
    const file = state.logs.files[state.selectedLogIndex];
    if (file !== undefined) {
      return file.name;
    } else {
      return undefined;
    }
  }, [state.logs, state.selectedLogIndex]);

  // Read header information for the logs
  // and then update
  useEffect(() => {
    const loadHeaders = async () => {
      log.debug("LOADING HEADERS");
      dispatch({
        type: "SET_HEADERS_LOADING",
        payload: true,
      });

      // Group into chunks
      const chunkSize = 8;
      const fileLists = [];
      for (let i = 0; i < state.logs.files.length; i += chunkSize) {
        let chunk = state.logs.files
          .slice(i, i + chunkSize)
          .map((log) => log.name);
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
          dispatch({
            type: "UPDATE_LOG_HEADERS",
            payload: updatedHeaders,
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
          // This will happen if the server disappears (e.g. inspect view is terminated)
          appContext.dispatch({
            type: "SET_STATUS",
            payload: { loading: false },
          });
        } else {
          console.log(e);
          appContext.dispatch({
            type: "SET_STATUS",
            payload: { loading: false, error: e as Error },
          });
        }
      }
      dispatch({
        type: "SET_HEADERS_LOADING",
        payload: false,
      });
    };

    loadHeaders();
  }, [state.logs, appContext.dispatch, dispatch]);

  return (
    <LogsContext.Provider
      value={{
        state,
        dispatch,
        refreshLogs,
        getState,
        selectLogFile,
        selectedLogFile,
      }}
    >
      {children}
    </LogsContext.Provider>
  );
};

// Custom hook to access log context
export const useLogsContext = (): LogsContextType => {
  const context = useContext(LogsContext);
  if (!context) {
    throw new Error("useLogContext must be used within a LogProvider");
  }
  return context;
};
