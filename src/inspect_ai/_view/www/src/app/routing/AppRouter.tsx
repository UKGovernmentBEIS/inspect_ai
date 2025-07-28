import { useEffect } from "react";
import {
  createHashRouter,
  Navigate,
  Outlet,
  useLocation,
} from "react-router-dom";
import { storeImplementation, useStore } from "../../state/store";
import { AppErrorBoundary } from "../AppErrorBoundary";
import { LogsPanel } from "../log-list/LogsPanel";
import { LogViewContainer } from "../log-view/LogViewContainer";
import { RouteDispatcher } from "./RouteDispatcher";
import {
  kLogRouteUrlPattern,
  kLogsRoutUrlPattern as kLogsRouteUrlPattern,
  kSampleRouteUrlPattern,
  kSampleUuidRouteUrlPattern,
} from "./url";

// Create a layout component that includes the RouteTracker
const AppLayout = () => {
  const location = useLocation();

  // Track changes to routes
  useEffect(() => {
    if (storeImplementation) {
      storeImplementation.getState().appActions.setUrlHash(location.pathname);
    }
  }, [location]);

  // Get log selection state from store
  const singleFileMode = useStore((state) => state.app.singleFileMode);

  // Single file mode is a legacy mode that is used when an explicit
  // file is passed via URL (task_file or log_file params) or via
  // embedded state (VSCode)
  if (singleFileMode) {
    return (
      <AppErrorBoundary>
        <LogViewContainer />
      </AppErrorBoundary>
    );
  }

  return (
    <AppErrorBoundary>
      <Outlet />
    </AppErrorBoundary>
  );
};

// Create router with our routes (using hash router for static deployments)
export const AppRouter = createHashRouter(
  [
    {
      path: "/",
      element: <AppLayout />,
      children: [
        {
          index: true, // This will match exactly the "/" path
          element: <LogsPanel />,
        },
        {
          path: kLogsRouteUrlPattern,
          element: <LogsPanel />,
        },
        {
          path: kLogRouteUrlPattern,
          element: <RouteDispatcher />,
        },
        {
          path: kSampleRouteUrlPattern,
          element: <LogViewContainer />,
        },
        {
          path: kSampleUuidRouteUrlPattern,
          element: <LogViewContainer />,
        },
      ],
    },
    {
      path: "*",
      element: <Navigate to="/" replace />,
    },
  ],
  { basename: "" },
);
