import { createHashRouter, Navigate } from "react-router";
import { LogViewContainer } from "./log-view/LogViewContainer";

// Create router with our routes (using hash router for static deployments)
export const AppRouter = createHashRouter(
  [
    {
      path: "/",
      element: <LogViewContainer />,
      children: [],
    },
    {
      path: "/logs/:logPath/:tabId?",
      element: <LogViewContainer />,
    },
    {
      path: "/logs/:logPath/:tabId?/sample/:sampleId/:epoch?",
      element: <LogViewContainer />,
    },
    {
      path: "*",
      element: <Navigate to="/" replace />,
    },
  ],
  { basename: "" },
);
