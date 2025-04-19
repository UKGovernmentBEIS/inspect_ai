import { EvalLogHeader, LogFiles } from "../client/api/types";
import { createLogger } from "../utils/logger";
import { createPolling } from "../utils/polling";
import { StoreState } from "./store";

// The logger
const log = createLogger("logsPolling");

export function createLogsPolling(
  get: () => StoreState,
  _set: (fn: (state: StoreState) => void) => void,
) {
  // Tracks the currently polling instance
  let currentPolling: ReturnType<typeof createPolling> | null = null;

  // Are we active
  let isActive = true;

  // Function to start polling for a specific log file
  const startPolling = (logFiles: LogFiles) => {
    // Get the api
    const api = get().api;
    if (!api) {
      throw new Error("Failed to start polling - no API");
    }

    // Stop any existing polling
    if (currentPolling) {
      currentPolling.stop();
    }

    // note that we're active
    isActive = true;

    log.debug("LOADING HEADERS");
    get().logsActions.setHeadersLoading(true);

    // Group into chunks
    const chunkSize = 8;
    const fileLists: string[][] = [];

    for (let i = 0; i < logFiles.files.length; i += chunkSize) {
      const chunk = logFiles.files
        .slice(i, i + chunkSize)
        .map((logFile) => logFile.name);
      fileLists.push(chunk);
    }
    const totalLen = fileLists.length;

    // Create a new polling instance
    currentPolling = createPolling(
      `LogHeaders`,
      async () => {
        if (!isActive) {
          get().logsActions.setHeadersLoading(false);
          return false; // Stop polling
        }

        log.debug(`POLL HEADERS`);

        const currentFileList = fileLists.shift();
        if (currentFileList) {
          log.debug(
            `LOADING ${totalLen - fileLists.length} of ${totalLen} CHUNKS`,
          );
          const headers = await api.get_log_headers(currentFileList);
          const updatedHeaders: Record<string, EvalLogHeader> = {};

          headers.forEach((header, index) => {
            const logFile = currentFileList[index];
            updatedHeaders[logFile] = header as EvalLogHeader;
          });
          get().logsActions.updateLogHeaders(updatedHeaders);
        } else {
          // Stop polling
          get().logsActions.setHeadersLoading(false);
          return false;
        }

        if (!isActive) {
          get().logsActions.setHeadersLoading(false);
          return false; // Stop polling
        }

        // Continue polling by default
        return true;
      },
      {
        maxRetries: 10,
        interval: 5,
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
    log.debug(`CLEANUP`);
    isActive = false;
    stopPolling();
  };

  return {
    startPolling,
    stopPolling,
    cleanup,
  };
}
