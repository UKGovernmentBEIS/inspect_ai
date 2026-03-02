import { lazy, Suspense, useEffect } from "react";
import {
  createHashRouter,
  Navigate,
  Outlet,
  useLocation,
} from "react-router-dom";
import { storeImplementation, useStore } from "../../state/store";
import { AppErrorBoundary } from "../AppErrorBoundary";
import { RouteDispatcher } from "./RouteDispatcher";
import { SamplesRouter } from "./SamplesRouter";
import {
  kLogRouteUrlPattern,
  kLogsRoutUrlPattern as kLogsRouteUrlPattern,
  useLogRouteParams,
} from "./url";

const LogsPanel = lazy(() =>
  import("../log-list/LogsPanel").then((m) => ({ default: m.LogsPanel })),
);
const LogViewContainer = lazy(() =>
  import("../log-view/LogViewContainer").then((m) => ({
    default: m.LogViewContainer,
  })),
);
const LogSampleDetailView = lazy(() =>
  import("../log-view/LogSampleDetailView").then((m) => ({
    default: m.LogSampleDetailView,
  })),
);

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

  // Get route params to check for sample detail routes
  const { sampleId, epoch, sampleUuid } = useLogRouteParams();

  // Single file mode is a legacy mode that is used when an explicit
  // file is passed via URL (task_file or log_file params) or via
  // embedded state (VSCode)
  if (singleFileMode) {
    // Check if this is a sample detail URL
    const isSampleDetail = (sampleId && epoch) || sampleUuid;

    return (
      <AppErrorBoundary>
        <Suspense fallback={null}>
          {isSampleDetail ? <LogSampleDetailView /> : <LogViewContainer />}
        </Suspense>
      </AppErrorBoundary>
    );
  }

  return (
    <AppErrorBoundary>
      <Suspense fallback={null}>
        <Outlet />
      </Suspense>
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
          element: <LogsPanel maybeShowSingleLog={true} />,
        },
        {
          path: kLogsRouteUrlPattern,
          element: <LogsPanel />,
        },
        {
          // This matches all /logs/* paths including sample detail URLs
          // The RouteDispatcher parses the path and routes to the appropriate component
          path: kLogRouteUrlPattern,
          element: <RouteDispatcher />,
        },
        {
          path: "/samples/*",
          element: <SamplesRouter />,
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
