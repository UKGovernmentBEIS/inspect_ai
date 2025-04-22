import { useEffect } from "react";
import {
  createHashRouter,
  Navigate,
  Outlet,
  useLocation,
} from "react-router-dom";
import { storeImplementation } from "../../state/store";
import { AppErrorBoundary } from "../AppErrorBoundary";
import { LogViewContainer } from "../log-view/LogViewContainer";
import { kLogRouteUrlPattern, kSampleRouteUrlPattern } from "./url";

// Create a layout component that includes the RouteTracker
const AppLayout = () => {
  const location = useLocation();

  // Track changes to routes
  useEffect(() => {
    if (storeImplementation) {
      storeImplementation.getState().appActions.setUrlHash(location.pathname);
    }
  }, [location]);

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
          element: <LogViewContainer />,
        },
        {
          path: kLogRouteUrlPattern,
          element: <LogViewContainer />,
        },
        {
          path: kSampleRouteUrlPattern,
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
