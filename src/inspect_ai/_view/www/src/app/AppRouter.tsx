import { useEffect } from "react";
import { createHashRouter, Navigate, Outlet, useLocation } from "react-router";
import { storeImplementation } from "../state/store";
import { AppErrorBoundary } from "./AppErrorBoundary";
import { LogViewContainer } from "./log-view/LogViewContainer";

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
      element: <AppLayout />, // Use the layout component
      loader: () => {
        // See if there is a hash that has been stored
        // and reload it (this is because VSCode will restore
        // the base URL when re-opening a tab that has been backgrounded)
        if (!storeImplementation) {
          // Handle the case where store isn't initialized yet
          return { initialRoute: null };
        }

        const storedHash = storeImplementation.getState().app.urlHash;
        return { initialRoute: storedHash };
      },
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
