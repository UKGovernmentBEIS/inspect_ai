import { Timeout } from "../types/log";
import { createLogger } from "./logger";

export interface PollingOptions {
  maxRetries: number;
  interval: number;
}

export interface Polling {
  start: () => void;
  stop: () => void;
}

// First, create a more robust polling utility
export const createPolling = (
  name: string,
  callback: () => Promise<boolean>,
  options: PollingOptions,
): Polling => {
  const log = createLogger(`Polling ${name}`);

  const { maxRetries, interval } = options;
  let timeoutId: Timeout = null;
  let retryCount = 0;
  let isPolling = false;

  const calculateBackoff = (retryCount: number) => {
    return Math.min(interval * Math.pow(2, retryCount) * 1000, 60000);
  };

  const stop = () => {
    if (timeoutId) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
    log.debug("Stop Polling");
    isPolling = false;
  };

  const poll = async () => {
    if (!isPolling) {
      return;
    }

    try {
      log.debug("Poll");
      const shouldContinue = await callback();

      if (shouldContinue === false) {
        stop();
        return;
      }

      // Reset retry count on success
      retryCount = 0;
      timeoutId = setTimeout(poll, interval * 1000);
    } catch (e) {
      retryCount += 1;

      if (retryCount >= maxRetries) {
        log.error(`Polling stopped after ${maxRetries} failed attempts`);
        stop();
        return;
      }

      const backoffTime = calculateBackoff(retryCount);
      log.debug(
        `Retry ${retryCount}/${maxRetries}, backoff: ${backoffTime / 1000}s`,
      );
      timeoutId = setTimeout(poll, backoffTime);
    }
  };

  const start = () => {
    if (isPolling) {
      return;
    }
    log.debug("Start Polling");
    isPolling = true;
    poll();
  };

  return { start, stop };
};
