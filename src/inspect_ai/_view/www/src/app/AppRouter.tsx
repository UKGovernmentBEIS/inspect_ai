import { createHashRouter, Navigate } from "react-router";
import { AppErrorBoundary } from "./AppErrorBoundary";
import { LogViewContainer } from "./log-view/LogViewContainer";

// Create router with our routes (using hash router for static deployments)
export const AppRouter = createHashRouter(
  [
    {
      path: "/",
      element: (
        <AppErrorBoundary>
          <LogViewContainer />
        </AppErrorBoundary>
      ),
      children: [],
    },
    {
      path: "/logs/:logPath/:tabId?",
      element: (
        <AppErrorBoundary>
          <LogViewContainer />
        </AppErrorBoundary>
      ),
    },
    {
      path: "/logs/:logPath/:tabId?/sample/:sampleId/:epoch?",
      element: (
        <AppErrorBoundary>
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
