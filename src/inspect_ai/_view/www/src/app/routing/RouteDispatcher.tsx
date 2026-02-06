import { FC } from "react";
import { FlowPanel } from "../flow/FlowPanel";
import { LogsPanel } from "../log-list/LogsPanel";
import { LogViewContainer } from "../log-view/LogViewContainer";
import { useLogRouteParams } from "./url";

/**
 * RouteDispatcher component that determines which view to show based on the route params.
 *
 * Note: Sample detail URLs (/logs/path/samples/sample/id/epoch) are handled by
 * explicit routes in AppRouter.tsx that route directly to LogSampleDetailView.
 *
 * Routes to:
 * - FlowPanel: for flow files (.yaml/.yml)
 * - LogViewContainer: for log files (.eval/.json)
 * - LogsPanel: for directory views
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
