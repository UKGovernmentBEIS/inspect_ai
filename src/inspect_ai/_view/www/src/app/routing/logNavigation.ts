import { useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useStore } from "../../state/store";
import { logsUrl, logsUrlRaw } from "./url";

export const useLogNavigation = () => {
  const navigate = useNavigate();
  const { logPath } = useParams<{ logPath: string }>();
  const logDir = useStore((state) => state.logs.logDir);
  const loadedLog = useStore((state) => state.log.loadedLog);

  const selectTab = useCallback(
    (tabId: string) => {
      // Only update URL if we have a loaded log
      if (loadedLog && logPath) {
        // We already have the logPath from params, just navigate to the tab
        const url = logsUrlRaw(logPath, tabId);
        navigate(url);
      } else if (loadedLog) {
        // Fallback to constructing the path if needed
        const url = logsUrl(loadedLog, logDir, tabId);
        navigate(url);
      }
    },
    [loadedLog, logPath, logDir, navigate],
  );

  return {
    selectTab,
  };
};
