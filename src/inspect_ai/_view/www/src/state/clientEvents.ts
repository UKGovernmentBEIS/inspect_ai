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
  const pendingLogFiles = new Set<LogFile>();

  const refreshPendingLogFiles = useCallback(async () => {
    if (isRefreshing) {
      return;
    }

    do {
      try {
        const logFiles = [...pendingLogFiles];
        pendingLogFiles.clear();

        isRefreshing = true;

        // Refresh the list of log files
        log.debug("Refresh Log Files");
        await refreshLogs();

        const toRefresh: LogFile[] = [];
        for (const logFile of logFiles) {
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
    } while (pendingLogFiles.size > 0);
  }, [logHeaders, refreshLogs, loadHeaders]);

  // Refresh logs and clear pending in a single transaction
  const refreshLogFiles = useCallback(
    async (logFiles: LogFile[]) => {
      logFiles.forEach((file) => pendingLogFiles.add(file));
      refreshPendingLogFiles();
    },
    [logHeaders, refreshLogs, refreshPendingLogFiles],
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
