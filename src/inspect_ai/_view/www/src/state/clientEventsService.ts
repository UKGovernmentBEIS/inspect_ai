import { LogHandle } from "../client/api/types";
import { createLogger } from "../utils/logger";
import { createPolling } from "../utils/polling";

const log = createLogger("Client-Events-Service");

const kRetries = 10;
const kPollingInterval = 5;
const kRefreshEvent = "refresh-evals";

class ClientEventsService {
  private currentPolling: ReturnType<typeof createPolling> | null = null;
  private abortController: AbortController | null = null;
  private isRefreshing = false;
  private pendingLogs = new Set<LogHandle>();
  private onRefreshCallback: ((logs: LogHandle[]) => Promise<void>) | null =
    null;

  setRefreshCallback(callback: (logs: LogHandle[]) => Promise<void>) {
    this.onRefreshCallback = callback;
  }

  private async refreshPendingLogFiles() {
    if (this.isRefreshing || !this.onRefreshCallback) {
      return;
    }

    do {
      try {
        const logFiles = [...this.pendingLogs];
        this.pendingLogs.clear();
        this.isRefreshing = true;

        // Call the refresh callback
        await this.onRefreshCallback(logFiles);
      } finally {
        this.isRefreshing = false;
      }
    } while (this.pendingLogs.size > 0);
  }

  private async refreshLogFiles(logs: LogHandle[]) {
    logs.forEach((file) => this.pendingLogs.add(file));
    await this.refreshPendingLogFiles();
  }

  startPolling(logs: LogHandle[], api: any) {
    // Stop any existing polling
    this.stopPolling();

    this.abortController = new AbortController();

    let pollingCount = 1;
    this.currentPolling = createPolling(
      `Client-Events`,
      async () => {
        if (this.abortController?.signal.aborted) {
          log.debug(`Component unmounted, stopping poll for client events`);
          return false;
        }

        log.debug(`Polling client events`);
        const events = await api?.client_events();
        log.debug(`Received events`, events);

        if (this.abortController?.signal.aborted) {
          log.debug(`Polling aborted, stopping poll for client events`);
          return false;
        }

        if ((events || []).includes(kRefreshEvent)) {
          await this.refreshLogFiles(logs);
        }

        if (pollingCount++ % 10 === 0) {
          await this.refreshLogFiles(logs);
        }

        return true;
      },
      {
        maxRetries: kRetries,
        interval: kPollingInterval,
      },
    );

    this.currentPolling.start();
  }

  stopPolling() {
    if (this.currentPolling) {
      this.currentPolling.stop();
      this.currentPolling = null;
    }
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }
  }

  cleanup() {
    log.debug(`Cleanup`);
    this.stopPolling();
    this.pendingLogs.clear();
    this.onRefreshCallback = null;
  }
}

// Singleton instance
export const clientEventsService = new ClientEventsService();
