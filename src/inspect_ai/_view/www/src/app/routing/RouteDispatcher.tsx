import { FC } from "react";
import { FlowPanel } from "../flow/FlowPanel";
import { LogsPanel } from "../log-list/LogsPanel";
import { LogViewContainer } from "../log-view/LogViewContainer";
import { useLogRouteParams } from "./url";

/**
 * RouteDispatcher component that determines whether to show FlowPanel, LogsPanel or LogViewContainer
 * based on the logPath parameter. If the path ends with .yaml/.yml, it shows the FlowPanel.
 * If logPath ends with .eval or .json, it shows the individual log view.
 * Otherwise, it shows the logs directory view.
 */
export const RouteDispatcher: FC = () => {
  const { logPath } = useLogRouteParams();

  // If no logPath is provided, show the logs directory view
  if (!logPath) {
    return <LogsPanel />;
  }

  // Check if the path ends with .yaml or .yml (indicating it's a flow file)
  const isFlowFile = logPath.endsWith(".yaml") || logPath.endsWith(".yml");

  // If it's a flow file, show the FlowPanel
  if (isFlowFile) {
    return <FlowPanel />;
  }

  // Check if the path ends with .eval or .json (indicating it's a log file)
  const isLogFile = logPath.endsWith(".eval") || logPath.endsWith(".json");

  // Route to the appropriate component
  if (isLogFile) {
    return <LogViewContainer />;
  } else {
    return <LogsPanel />;
  }
};
