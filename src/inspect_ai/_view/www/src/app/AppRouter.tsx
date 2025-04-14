import { createHashRouter, Navigate, Outlet } from "react-router";
import { AppErrorBoundary } from "./AppErrorBoundary";
import { LogViewContainer } from "./log-view/LogViewContainer";
import { RouteTracker } from "./routing/RouteTracker";

// Create a layout component that includes the RouteTracker
const AppLayout = () => {
  return (
    <AppErrorBoundary>
      <RouteTracker />
      <Outlet />
    </AppErrorBoundary>
  );
};

// Create router with our routes (using hash router for static deployments)
export const AppRouter = createHashRouter(
  [
    {
      path: "/",
      element: <AppLayout />, // Use the layout component
      children: [
        {
          index: true, // This will match exactly the "/" path
          element: <LogViewContainer />,
        },
        {
          path: "logs/:logPath/:tabId?",
          element: <LogViewContainer />,
        },
        {
          path: "logs/:logPath/:tabId?/sample/:sampleId/:epoch?",
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
