import { FC } from "react";
import { FlowPanel } from "../flow/FlowPanel";
import { LogsPanel } from "../log-list/LogsPanel";
import { LogSampleDetailView } from "../log-view/LogSampleDetailView";
import { LogViewContainer } from "../log-view/LogViewContainer";
import { useLogRouteParams } from "./url";

/**
 * RouteDispatcher component that determines which view to show based on the route params.
 *
 * Routes to:
 * - LogSampleDetailView: for sample detail URLs (/logs/path/samples/sample/id/epoch)
 * - FlowPanel: for flow files (.yaml/.yml)
 * - LogViewContainer: for log files (.eval/.json)
 * - LogsPanel: for directory views
 */
export const RouteDispatcher: FC = () => {
  const { logPath, sampleId, epoch, sampleUuid } = useLogRouteParams();

  // If no logPath is provided, show the logs directory view
  if (!logPath) {
    return <LogsPanel />;
  }

  // Check if this is a sample detail URL
  // Sample URLs have sampleId + epoch, or sampleUuid
  if ((sampleId && epoch) || sampleUuid) {
    return <LogSampleDetailView />;
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
