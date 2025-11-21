import { FC } from "react";
import { useSearchParams } from "react-router-dom";
import { FlowPanel } from "../flow/FlowPanel";
import { LogsPanel } from "../log-list/LogsPanel";
import { LogViewContainer } from "../log-view/LogViewContainer";
import { useLogRouteParams } from "./url";

/**
 * RouteDispatcher component that determines whether to show FlowPanel, LogsPanel or LogViewContainer
 * based on the logPath parameter and URL search params. If ?flow query param is present, it shows
 * the FlowPanel. If logPath ends with .eval or .json, it shows the individual log view.
 * Otherwise, it shows the logs directory view.
 */
export const RouteDispatcher: FC = () => {
  const { logPath } = useLogRouteParams();
  const [searchParams] = useSearchParams();

  // Check if the ?flow query parameter is present
  const hasFlowParam = searchParams.has("flow");

  // If no logPath is provided, show the logs directory view or flow panel
  if (!logPath) {
    return hasFlowParam ? <FlowPanel /> : <LogsPanel />;
  }

  // Check if the path ends with .eval or .json (indicating it's a log file)
  const isLogFile = logPath.endsWith(".eval") || logPath.endsWith(".json");

  // Route to the appropriate component
  if (isLogFile) {
    return <LogViewContainer />;
  } else {
    return hasFlowParam ? <FlowPanel /> : <LogsPanel />;
  }
};
