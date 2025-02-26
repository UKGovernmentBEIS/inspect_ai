import { createContext, useCallback, useContext, useReducer } from "react";
import { ClientAPI, EvalLogHeader, LogFiles } from "./api/types";

// Define action types
type LogsAction =
  | { type: "SET_LOGS"; payload: LogFiles }
  | { type: "SET_LOG_HEADERS"; payload: Record<string, EvalLogHeader> }
  | { type: "SET_HEADERS_LOADING"; payload: boolean }
  | { type: "SET_SELECTED_LOG_INDEX"; payload: number }
  | { type: "UPDATE_LOG_HEADERS"; payload: Record<string, EvalLogHeader> };

// Define the state shape
export interface LogsState {
  logs: LogFiles;
  logHeaders: Record<string, EvalLogHeader>;
  headersLoading: boolean;
  selectedLogIndex?: number;
}

// Initial state
const initialLogsState: LogsState = {
  logs: { log_dir: "", files: [] },
  logHeaders: {},
  headersLoading: false,
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
  dispatch: React.Dispatch<LogsAction>;
  refreshLogs: () => Promise<void>;
  getState: () => { logs: LogsState };
}

const LogsContext = createContext<LogsContextType | undefined>(undefined);

interface LogsProviderProps {
  initialState?: { logs?: LogsState };
  children: React.ReactNode;
  api: ClientAPI;
}

export const LogsProvider: React.FC<LogsProviderProps> = ({
  children,
  initialState,
  api,
}) => {
  const [state, dispatch] = useReducer(
    logsReducer,
    initialState
      ? { ...initialLogsState, ...initialState.logs }
      : initialLogsState,
  );

  const getState = () => {
    return { logs: state };
  };

  // Function to refresh logs (simulated API call)
  const refreshLogs = useCallback(async () => {
    dispatch({ type: "SET_HEADERS_LOADING", payload: true });
    try {
      // Replace this with an actual API call
      const newLogs: LogFiles = { log_dir: "updated_dir", files: [] };
      dispatch({ type: "SET_LOGS", payload: newLogs });
    } catch (error) {
      console.error("Error refreshing logs:", error);
    } finally {
      dispatch({ type: "SET_HEADERS_LOADING", payload: false });
    }
  }, []);

  return (
    <LogsContext.Provider value={{ state, dispatch, refreshLogs, getState }}>
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
