import { createLogger } from "../utils/logger";
import { createPolling } from "../utils/polling";
import { StoreState } from "./store";

// The logger
const log = createLogger("logPolling");

export function createLogPolling(
  get: () => StoreState,
  set: (fn: (state: StoreState) => void) => void,
) {
  // Tracks the currently polling instance
  let currentPolling: ReturnType<typeof createPolling> | null = null;

  // Are we active
  let isActive = true;

  // Function to start polling for a specific log file
  const startPolling = (logFileName: string) => {
    // Stop any existing polling
    if (currentPolling) {
      currentPolling.stop();
    }

    // note that we're active
    isActive = true;

    // Create a new polling instance
    currentPolling = createPolling(
      `PendingSamples-${logFileName}`,
      async () => {
        if (!isActive) {
          log.debug(`Component unmounted, stopping poll for: ${logFileName}`);
          return false; // Stop polling
        }

        const state = get();
        const api = state.api;

        // Don't proceed if API doesn't support it
        if (!api?.get_log_pending_samples) return false;

        const currentEtag = get().log.pendingSampleSummaries?.etag;

        log.debug(`POLL RUNNING SAMPLES: ${logFileName}`);

        if (!isActive) {
          return false; // Stop polling
        }

        const pendingSamples = await api.get_log_pending_samples(
          logFileName,
          currentEtag,
        );

        if (!isActive) {
          return false; // Stop polling
        }

        if (pendingSamples.status === "OK" && pendingSamples.pendingSamples) {
          // Update state with new pending samples
          set((state) => {
            state.log.pendingSampleSummaries = pendingSamples.pendingSamples;
          });

          // Refresh the log to get latest data
          get().logActions.refreshLog();

          // Continue polling
          return true;
        } else if (pendingSamples.status === "NotFound") {
          log.debug(`STOP POLLING RUNNING SAMPLES: ${logFileName}`);

          // Clear pending summaries
          clearPendingSummaries(logFileName);

          // Stop polling
          return false;
        }

        // Continue polling by default
        return true;
      },
      {
        maxRetries: 10,
        interval: get().log.pendingSampleSummaries?.refresh || 2,
      },
    );

    // Start the polling
    currentPolling.start();
  };

  // Clear pending summaries
  const clearPendingSummaries = (logFileName: string) => {
    if (!isActive) {
      return false; // Stop polling
    }

    const pendingSampleSummaries = get().log.pendingSampleSummaries;
    if ((pendingSampleSummaries?.samples.length || 0) > 0) {
      log.debug(`CLEAR PENDING: ${logFileName}`);
      set((state) => {
        state.log.pendingSampleSummaries = {
          samples: [],
          refresh: pendingSampleSummaries?.refresh || 2,
        };
      });
      get().logActions.refreshLog();
    }
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
    log.debug(`CLEANUP`);
    isActive = false;
    stopPolling();
  };

  return {
    startPolling,
    stopPolling,
    clearPendingSummaries,
    cleanup,
  };
}
