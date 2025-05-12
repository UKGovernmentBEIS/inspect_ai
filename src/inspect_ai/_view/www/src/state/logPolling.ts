import { createLogger } from "../utils/logger";
import { createPolling } from "../utils/polling";
import { StoreState } from "./store";

// The logger
const log = createLogger("logPolling");

const kRetries = 10;
const kPollingInterval = 2;

export function createLogPolling(
  get: () => StoreState,
  set: (fn: (state: StoreState) => void) => void,
) {
  // Tracks the currently polling instance
  let currentPolling: ReturnType<typeof createPolling> | null = null;

  // handle aborts
  let abortController: AbortController;

  // Refresh logs and clear pending in a single transaction
  const refreshLog = async (logFileName: string, clearPending = false) => {
    if (abortController?.signal.aborted) {
      return false;
    }

    const state = get();
    const api = state.api;
    const selectedLogFile = state.logs.selectedLogFile;

    if (!api || !selectedLogFile) {
      return false;
    }

    log.debug(`refresh: ${selectedLogFile}`);

    try {
      const logContents = await api.get_log_summary(selectedLogFile);

      set((state) => {
        // Set the log summary
        state.log.selectedLogSummary = logContents;
        log.debug(
          `Setting refreshed summary ${logContents.sampleSummaries.length} samples`,
          logContents,
        );

        // Clear pending summaries if requested
        if (clearPending) {
          const pendingSampleSummaries = state.log.pendingSampleSummaries;
          if ((pendingSampleSummaries?.samples.length || 0) > 0) {
            log.debug(
              `Clearing pending summaries during refresh for: ${logFileName}`,
            );
            state.log.pendingSampleSummaries = {
              samples: [],
              refresh: pendingSampleSummaries?.refresh || 2,
            };
          }
        }
      });

      return true;
    } catch (error) {
      log.error("Error refreshing log:", error);
      return false;
    }
  };

  // Function to start polling for a specific log file
  const startPolling = (logFileName: string) => {
    // Stop any existing polling
    if (currentPolling) {
      currentPolling.stop();
    }

    // note that we're active
    abortController = new AbortController();

    // Track whether we ever polled
    let loadedPendingSamples = false;

    // Create a new polling instance
    currentPolling = createPolling(
      `PendingSamples-${logFileName}`,
      async () => {
        if (abortController.signal.aborted) {
          log.debug(`Component unmounted, stopping poll for: ${logFileName}`);
          return false;
        }

        // The state for polling
        const state = get();

        // Don't proceed if API doesn't support it
        const api = state.api;
        if (!api?.get_log_pending_samples) {
          return false;
        }

        if (abortController.signal.aborted) {
          return false;
        }

        // Fetch pending samples
        log.debug(`Polling running samples: ${logFileName}`);
        const currentEtag = get().log.pendingSampleSummaries?.etag;
        const pendingSamples = await api.get_log_pending_samples(
          logFileName,
          currentEtag,
        );
        log.debug(`Received pending samples`, pendingSamples);

        if (abortController.signal.aborted) {
          return false;
        }

        if (pendingSamples.status === "OK" && pendingSamples.pendingSamples) {
          loadedPendingSamples = true;

          // Update state with new pending samples
          set((state) => {
            state.log.pendingSampleSummaries = pendingSamples.pendingSamples;
          });

          // Refresh the log to get latest data
          await refreshLog(logFileName, false);

          // Continue polling
          return true;
        } else if (pendingSamples.status === "NotFound") {
          // The eval has completed (no more events/pending samples will be delivered)
          log.debug(`Stop polling running samples: ${logFileName}`);

          // Clear pending summaries and refresh in one transaction
          if (
            loadedPendingSamples ||
            state.log.selectedLogSummary?.status === "started"
          ) {
            log.debug(`Refresh log: ${logFileName}`);
            await refreshLog(logFileName, true);
          }

          // Stop polling
          return false;
        }

        // Continue polling by default
        return true;
      },
      {
        maxRetries: kRetries,
        interval: get().log.pendingSampleSummaries?.refresh || kPollingInterval,
      },
    );

    // Start the polling
    currentPolling.start();
  };

  // Clear pending summaries (now using the transactional approach)
  const clearPendingSummaries = (logFileName: string) => {
    if (abortController.signal.aborted) {
      return false;
    }

    const pendingSampleSummaries = get().log.pendingSampleSummaries;
    if ((pendingSampleSummaries?.samples.length || 0) > 0) {
      log.debug(`Clear pending: ${logFileName}`);
      return refreshLog(logFileName, true);
    }

    return false;
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
    abortController.abort();
    stopPolling();
  };

  return {
    startPolling,
    stopPolling,
    clearPendingSummaries,
    cleanup,
    // Expose the refresh function so components can use it directly
    refreshLog: (clearPending = false) =>
      refreshLog(get().logs.selectedLogFile || "", clearPending),
  };
}
