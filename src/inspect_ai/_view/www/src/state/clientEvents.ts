import { useCallback, useEffect } from "react";
import { LogHandle } from "../client/api/types";
import { createLogger } from "../utils/logger";
import { clientEventsService } from "./clientEventsService";
import { useLogs } from "./hooks";
import { useStore } from "./store";

const log = createLogger("Client-Events");

export function useClientEvents() {
  const syncLogs = useStore((state) => state.logsActions.syncLogs);
  const logPreviews = useStore((state) => state.logs.logPreviews);
  const api = useStore((state) => state.api);
  const { loadLogOverviews } = useLogs();

  // Set up the refresh callback for the service
  const refreshCallback = useCallback(
    async (logs: LogHandle[]) => {
      // Refresh the list of log files
      log.debug("Refresh Log Files");
      await syncLogs();

      const toRefresh: LogHandle[] = [];
      for (const log of logs) {
        const header = logPreviews[log.name];
        if (!header || header.status === "started") {
          toRefresh.push(log);
        }
      }

      // Refresh any logFiles that are currently being watched
      if (toRefresh.length > 0) {
        log.debug(`Refreshing ${toRefresh.length} log files`, toRefresh);
        await loadLogOverviews(toRefresh);
      }
    },
    [logPreviews, syncLogs, loadLogOverviews],
  );

  // Update the service's refresh callback when dependencies change
  useEffect(() => {
    clientEventsService.setRefreshCallback(refreshCallback);
  }, [refreshCallback]);

  // Wrapper functions that call the service
  const startPolling = useCallback(
    (logs: LogHandle[]) => {
      clientEventsService.startPolling(logs, api);
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
