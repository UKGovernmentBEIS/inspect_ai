import { createHashRouter, Navigate } from "react-router";
import { AppErrorBoundary } from "./AppErrorBoundary";
import { LogViewContainer } from "./log-view/LogViewContainer";
import { RouteTracker } from "./routing/RouteTracker";

// Create router with our routes (using hash router for static deployments)
export const AppRouter = createHashRouter(
  [
    {
      path: "/",
      element: (
        <AppErrorBoundary>
          <RouteTracker />
          <LogViewContainer />
        </AppErrorBoundary>
      ),
      children: [],
    },
    {
      path: "/logs/:logPath/:tabId?",
      element: (
        <AppErrorBoundary>
          <RouteTracker />
          <LogViewContainer />
        </AppErrorBoundary>
      ),
    },
    {
      path: "/logs/:logPath/:tabId?/sample/:sampleId/:epoch?",
      element: (
        <AppErrorBoundary>
          <RouteTracker />
          <LogViewContainer />
        </AppErrorBoundary>
      ),
    },
    {
      path: "*",
      element: <Navigate to="/" replace />,
    },
  ],
  { basename: "" },
);
