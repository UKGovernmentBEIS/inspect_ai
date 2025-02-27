import {
  createContext,
  Dispatch,
  FC,
  ReactNode,
  useContext,
  useReducer,
} from "react";
import { Capabilities } from "./api/types";
import { AppState, AppStatus } from "./types";
import { clearDocumentSelection } from "./utils/browser";

// Define the initial state
const initialAppState: AppState = {
  status: { loading: false },
  offcanvas: false,
  showFind: false,
};

// Define action types
type AppAction =
  | { type: "SET_STATUS"; payload: AppStatus }
  | { type: "SET_OFFCANVAS"; payload: boolean }
  | { type: "SET_SHOW_FIND"; payload: boolean }
  | { type: "HIDE_FIND" };

// Create the reducer
function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case "SET_STATUS":
      return { ...state, status: action.payload };
    case "SET_OFFCANVAS":
      return { ...state, offcanvas: action.payload };
    case "SET_SHOW_FIND":
      return { ...state, showFind: action.payload };
    case "HIDE_FIND":
      clearDocumentSelection();
      return { ...state, showFind: false };
    default:
      return state;
  }
}

// Create the context
interface AppContextType {
  state: AppState;
  dispatch: Dispatch<AppAction>;
  capabilities: Capabilities;
  getState: () => { app: AppState };
}

const AppContext = createContext<AppContextType | undefined>(undefined);

// Create the provider
interface AppProviderProps {
  children: ReactNode;
  capabilities: Capabilities;
  initialState?: { app?: Partial<AppState> };
}

export const AppProvider: FC<AppProviderProps> = ({
  children,
  capabilities,
  initialState,
}) => {
  // Initialize with saved state or defaults

  const [state, dispatch] = useReducer(
    appReducer,
    initialState
      ? { ...initialAppState, ...initialState.app }
      : initialAppState,
  );

  // Function to get current state (for state saving)
  const getState = () => {
    return { app: state };
  };

  // Create the context value
  const contextValue: AppContextType = {
    state,
    dispatch,
    capabilities,
    getState,
  };

  return (
    <AppContext.Provider value={contextValue}>{children}</AppContext.Provider>
  );
};

// Create the hook
export const useAppContext = () => {
  const context = useContext(AppContext);
  if (context === undefined) {
    throw new Error("useAppContext must be used within an AppProvider");
  }
  return context;
};

// Helper functions for common actions
export const useAppActions = () => {
  const { dispatch } = useAppContext();

  return {
    setStatus: (status: AppStatus) =>
      dispatch({ type: "SET_STATUS", payload: status }),
    setOffcanvas: (show: boolean) =>
      dispatch({ type: "SET_OFFCANVAS", payload: show }),
    setShowFind: (show: boolean) =>
      dispatch({ type: "SET_SHOW_FIND", payload: show }),
    hideFind: () => dispatch({ type: "HIDE_FIND" }),
  };
};
