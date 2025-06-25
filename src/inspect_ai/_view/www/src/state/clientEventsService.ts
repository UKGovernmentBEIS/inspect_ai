import { LogFile } from "../client/api/types";
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
  private pendingLogFiles = new Set<LogFile>();
  private onRefreshCallback: ((logFiles: LogFile[]) => Promise<void>) | null =
    null;

  setRefreshCallback(callback: (logFiles: LogFile[]) => Promise<void>) {
    this.onRefreshCallback = callback;
  }

  private async refreshPendingLogFiles() {
    if (this.isRefreshing || !this.onRefreshCallback) {
      return;
    }

    do {
      try {
        const logFiles = [...this.pendingLogFiles];
        this.pendingLogFiles.clear();
        this.isRefreshing = true;

        // Call the refresh callback
        await this.onRefreshCallback(logFiles);
      } finally {
        this.isRefreshing = false;
      }
    } while (this.pendingLogFiles.size > 0);
  }

  private async refreshLogFiles(logFiles: LogFile[]) {
    logFiles.forEach((file) => this.pendingLogFiles.add(file));
    await this.refreshPendingLogFiles();
  }

  startPolling(logFiles: LogFile[], api: any) {
    // Stop any existing polling
    this.stopPolling();

    this.abortController = new AbortController();

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
          await this.refreshLogFiles(logFiles);
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
    this.pendingLogFiles.clear();
    this.onRefreshCallback = null;
  }
}

// Singleton instance
export const clientEventsService = new ClientEventsService();
