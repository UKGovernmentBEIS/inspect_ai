import { useCallback, useEffect } from "react";
import { LogFile } from "../client/api/types";
import { createLogger } from "../utils/logger";
import { clientEventsService } from "./clientEventsService";
import { useLogs } from "./hooks";
import { useStore } from "./store";

const log = createLogger("Client-Events");

export function useClientEvents() {
  const refreshLogs = useStore((state) => state.logsActions.refreshLogs);
  const logHeaders = useStore((state) => state.logs.logOverviews);
  const api = useStore((state) => state.api);
  const { loadHeaders } = useLogs();

  // Set up the refresh callback for the service
  const refreshCallback = useCallback(
    async (logFiles: LogFile[]) => {
      // Refresh the list of log files
      log.debug("Refresh Log Files");
      await refreshLogs();

      const toRefresh: LogFile[] = [];
      for (const logFile of logFiles) {
        const header = logHeaders[logFile.name];
        if (!header || header.status === "started") {
          toRefresh.push(logFile);
        }
      }

      // Refresh any logFiles that are currently being watched
      if (toRefresh.length > 0) {
        log.debug(`Refreshing ${toRefresh.length} log files`, toRefresh);
        await loadHeaders(toRefresh);
      }
    },
    [logHeaders, refreshLogs, loadHeaders],
  );

  // Update the service's refresh callback when dependencies change
  useEffect(() => {
    clientEventsService.setRefreshCallback(refreshCallback);
  }, [refreshCallback]);

  // Wrapper functions that call the service
  const startPolling = useCallback(
    (logFiles: LogFile[]) => {
      clientEventsService.startPolling(logFiles, api);
    },
    [api],
  );

  const stopPolling = useCallback(() => {
    clientEventsService.stopPolling();
  }, []);

  const cleanup = useCallback(() => {
    clientEventsService.cleanup();
  }, []);

  // Cleanup when hook unmounts
  useEffect(() => {
    return () => {
      cleanup();
    };
  }, [cleanup]);

  return {
    startPolling,
    stopPolling,
    cleanup,
  };
}
