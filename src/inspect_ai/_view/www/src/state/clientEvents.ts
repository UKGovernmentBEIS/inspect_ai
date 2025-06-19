import { useCallback } from "react";
import { LogFile } from "../client/api/types";
import { createLogger } from "../utils/logger";
import { createPolling } from "../utils/polling";
import { useLogs } from "./hooks";
import { useStore } from "./store";

// The logger
const log = createLogger("Client-Events");

const kRetries = 10;
const kPollingInterval = 5;

const kRefreshEvent = "refresh-evals";

export function useClientEvents() {
  const refreshLogs = useStore((state) => state.logsActions.refreshLogs);
  const logHeaders = useStore((state) => state.logs.logHeaders);
  const api = useStore((state) => state.api);
  const { loadHeaders } = useLogs();

  // Tracks the currently polling instance
  let currentPolling: ReturnType<typeof createPolling> | null = null;

  // handle aborts
  let abortController: AbortController;

  // Track if refresh is in progress to prevent concurrent calls
  let isRefreshing = false;

  // Accumulate log files that arrive while refresh is in progress
  const pendingLogFiles = new Set<string>();

  // Refresh logs and clear pending in a single transaction
  const refreshLogFiles = useCallback(
    async (logFiles: LogFile[]) => {
      // If refresh is in progress, accumulate files for next refresh
      if (isRefreshing) {
        log.debug("Refresh already in progress, accumulating files");
        logFiles.forEach(file => pendingLogFiles.add(file.name));
        return;
      }

      isRefreshing = true;
      try {
        // Include any pending files from previous skipped calls
        const allLogFiles = [...logFiles];
        if (pendingLogFiles.size > 0) {
          log.debug(`Including ${pendingLogFiles.size} pending files`);
          for (const fileName of pendingLogFiles) {
            // Add pending file if not already in current batch
            if (!allLogFiles.some(f => f.name === fileName)) {
              allLogFiles.push({ name: fileName });
            }
          }
          pendingLogFiles.clear();
        }

        // Refresh the list of log files
        log.debug("Refresh Log Files");
        refreshLogs();

        const toRefresh: LogFile[] = [];
        for (const logFile of allLogFiles) {
          const header = logHeaders[logFile.name];
          if (
            !header ||
            header.status === "started" ||
            header.status === "error"
          ) {
            toRefresh.push(logFile);
          }
        }

        // Refresh any logFiles that are currently being watched
        if (toRefresh.length > 0) {
          log.debug(`Refreshing ${toRefresh.length} log files`, toRefresh);
          await loadHeaders(toRefresh);
        }
      } finally {
        isRefreshing = false;
      }
    },
    [logHeaders, refreshLogs],
  );

  // Function to start polling for a specific log file
  const startPolling = (logFiles: LogFile[]) => {
    // Stop any existing polling
    if (currentPolling) {
      currentPolling.stop();
    }

    // note that we're active
    abortController = new AbortController();

    // Create a new polling instance
    currentPolling = createPolling(
      `Client-Events`,
      async () => {
        if (abortController.signal.aborted) {
          log.debug(`Component unmounted, stopping poll for client events`);
          return false;
        }

        if (abortController.signal.aborted) {
          return false;
        }

        // Fetch pending samples
        log.debug(`Polling client events`);
        const events = await api?.client_events();
        log.debug(`Received events`, events);

        if (abortController.signal.aborted) {
          log.debug(`Polling aborted, stopping poll for client events`);
          return false;
        }

        if ((events || []).includes(kRefreshEvent)) {
          // Do the refresh
          await refreshLogFiles(logFiles);
        }

        // Continue polling
        return true;
      },
      {
        maxRetries: kRetries,
        interval: kPollingInterval,
      },
    );

    // Start the polling
    currentPolling.start();
  };

  // Stop polling
  const stopPolling = () => {
    if (currentPolling) {
      currentPolling.stop();
      currentPolling = null;
    }
  };

  // Method to call when component unmounts
  const cleanup = () => {
    log.debug(`Cleanup`);
    if (abortController) {
      abortController.abort();
    }
    stopPolling();
    pendingLogFiles.clear();
  };

  return {
    startPolling,
    stopPolling,
    cleanup,
  };
}
