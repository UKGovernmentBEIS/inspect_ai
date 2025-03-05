import { SampleSummary } from "../api/types";
import { sampleDataAdapter } from "../samples/sampleDataAdapter";
import { createLogger } from "../utils/logger";
import { createPolling } from "../utils/polling";
import { StoreState } from "./store";

// The logger
const log = createLogger("samplePolling");

export function createSamplePolling(
  get: () => StoreState,
  _set: (fn: (state: StoreState) => void) => void,
) {
  // Tracks the currently polling instance
  let currentPolling: ReturnType<typeof createPolling> | null = null;

  // Function to start polling for a specific log file
  const startPolling = (logFile: string, summary: SampleSummary) => {
    // Stop any existing polling first
    if (currentPolling) {
      currentPolling.stop();
    }

    log.debug(`POLLING RUNNING SAMPLE: ${summary.id}-${summary.epoch}`);

    // Create the polling callback
    const pollCallback = async () => {
      const api = get().api;
      if (!api) {
        throw new Error("Required API is missing");
      }

      if (!api.get_log_sample_data) {
        return false; // Stop polling
      }

      log.debug(`GET RUNNING SAMPLE: ${summary.id}-${summary.epoch}`);
      const sampleDataResponse = await api.get_log_sample_data(
        logFile,
        summary.id,
        summary.epoch,
      );

      if (sampleDataResponse?.status === "NotFound") {
        // Stop polling
        return false;
      }

      if (
        sampleDataResponse?.status === "OK" &&
        sampleDataResponse.sampleData
      ) {
        const adapter = sampleDataAdapter();
        adapter.addData(sampleDataResponse.sampleData);
        const events = adapter.resolvedEvents();
        const runningData = { events, summary };
        log.debug(`EVENTS: ${events.length}`);
        get().sampleActions.setRunningSampleData(runningData);
      }
      // Continue polling
      return true;
    };

    // Create the polling instance
    const name = `${logFile}:${summary.id}-${summary.epoch}`;
    const polling = createPolling(name, pollCallback, {
      maxRetries: 10,
      interval: 2, // 2 seconds
    });

    // Store the polling instance and start it
    currentPolling = polling;
    polling.start();
  };

  // Stop polling
  const stopPolling = () => {
    if (currentPolling) {
      currentPolling.stop();
      currentPolling = null;
    }
  };

  return {
    startPolling,
    stopPolling,
  };
}
