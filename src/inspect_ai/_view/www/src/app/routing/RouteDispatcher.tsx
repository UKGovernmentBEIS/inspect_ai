import { FC } from "react";
import { useParams } from "react-router-dom";
import { LogsPanel } from "../log-list/LogsPanel";
import { LogViewContainer } from "../log-view/LogViewContainer";

/**
 * RouteDispatcher component that determines whether to show LogsView or LogViewContainer
 * based on the logPath parameter. If logPath ends with .eval or .json, it shows the
 * individual log view. Otherwise, it shows the logs directory view.
 */
export const RouteDispatcher: FC = () => {
  const { logPath } = useParams<{ logPath?: string }>();

  // If no logPath is provided, show the logs directory view
  if (!logPath) {
    return <LogsPanel />;
  }

  // Decode the logPath in case it's URL encoded
  const decodedLogPath = decodeURIComponent(logPath);

  // Check if the path ends with .eval or .json (indicating it's a log file)
  const isLogFile =
    decodedLogPath.endsWith(".eval") || decodedLogPath.endsWith(".json");

  // Route to the appropriate component
  if (isLogFile) {
    return <LogViewContainer />;
  } else {
    return <LogsPanel />;
  }
};
