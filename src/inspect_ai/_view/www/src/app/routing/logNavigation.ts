import { useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useStore } from "../../state/store";
import { logUrl, logUrlRaw } from "./url";

export const useLogNavigation = () => {
  const navigate = useNavigate();
  const { logPath } = useParams<{ logPath: string }>();
  const logs = useStore((state) => state.logs.logs);
  const loadedLog = useStore((state) => state.log.loadedLog);

  const selectTab = useCallback(
    (tabId: string) => {
      // Only update URL if we have a loaded log
      if (loadedLog && logPath) {
        // We already have the logPath from params, just navigate to the tab
        const url = logUrlRaw(logPath, tabId);
        navigate(url);
      } else if (loadedLog) {
        // Fallback to constructing the path if needed
        const url = logUrl(loadedLog, logs.log_dir, tabId);
        navigate(url);
      }
    },
    [loadedLog, logPath, logs.log_dir, navigate],
  );

  return {
    selectTab,
  };
};
