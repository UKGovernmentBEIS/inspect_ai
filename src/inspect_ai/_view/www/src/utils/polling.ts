import { createLogger } from "./logger";

export interface PollingOptions {
  maxRetries: number;
  interval: number;
}

export interface Polling {
  name: string;
  start: () => void;
  stop: () => void;
}

export const createPolling = (
  name: string,
  callback: () => Promise<boolean>,
  options: PollingOptions,
): Polling => {
  const log = createLogger(`Polling ${name}`);

  const { maxRetries, interval } = options;
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  let retryCount = 0;
  // Are we currently polling
  let isPolling = false;

  // Are we stopped (e.g. cleaning up)
  let isStopped = false;

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
    isStopped = true;
  };

  const poll = async () => {
    try {
      log.debug("Poll");
      // Don't proceed if polling has been stopped
      if (!isPolling || isStopped) {
        return;
      }

      const shouldContinue = await callback();
      if (shouldContinue === false) {
        stop();
        return;
      }

      // Reset retry count on success
      retryCount = 0;
      if (!isPolling || isStopped) {
        return;
      }
      timeoutId = setTimeout(poll, interval * 1000);
    } catch (e) {
      // Don't retry if polling has been stopped
      if (!isPolling || isStopped) {
        return;
      }
      log.debug("Polling error occurred", e);

      retryCount += 1;

      if (retryCount >= maxRetries) {
        stop();
        throw new Error(
          `Gave up polling ${name} after ${maxRetries} attempts.`,
        );
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
    isStopped = false;
    poll();
  };

  return { name, start, stop };
};
