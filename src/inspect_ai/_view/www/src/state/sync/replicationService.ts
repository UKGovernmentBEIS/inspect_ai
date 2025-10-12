import {
  ClientAPI,
  LogDetails,
  LogHandle,
  LogPreview,
} from "../../client/api/types";
import { DatabaseService } from "../../client/database";
import { WorkQueue } from "../../utils/workQueue";

export interface ApplicationContext {
  setLogHandles: (logs: LogHandle[]) => void;
  getSelectedLog: () => LogHandle | undefined;
  setSelectedLogIndex: (index: number) => void;
  updateLogPreviews: (previews: Record<string, LogPreview>) => void;
}

export class ReplicationService {
  private _database: DatabaseService | undefined = undefined;
  private _api: ClientAPI | undefined = undefined;
  private _applicationContext: ApplicationContext | undefined = undefined;
  private _previewQueue: WorkQueue<LogHandle, LogPreview>;
  private _detailQueue: WorkQueue<LogHandle, LogDetails>;

  constructor() {
    this._previewQueue = new WorkQueue<LogHandle, LogPreview>({
      batchSize: 10,
      processingDelay: 100,
    });
    this._detailQueue = new WorkQueue<LogHandle, LogDetails>({
      batchSize: 3,
      processingDelay: 50,
    });

    // Set up the worker function
    this._previewQueue.setWorker(async (logHandles: LogHandle[]) => {
      if (!this._api) throw new Error("API not available");

      const previews = await this._api.get_log_summaries(
        logHandles.map((log) => log.name),
      );

      return previews;
    });
    this._detailQueue.setWorker(async (logHandles: LogHandle[]) => {
      if (!this._api) throw new Error("API not available");

      const details = await Promise.all(
        logHandles.map(async (log) => {
          try {
            const result = await this._api!.get_log_details(log.name);
            return result;
          } catch {
            return undefined;
          }
        }),
      );

      const allResults = details.filter((d) => d !== undefined);
      return allResults;
    });

    // Set up completion callback
    this._previewQueue.setOnComplete(
      (previews: LogPreview[], inputs: LogHandle[]) => {
        // Build preview map
        const previewMap: Record<string, LogPreview> = {};
        inputs.forEach((log, i) => {
          if (previews[i]) {
            previewMap[log.name] = previews[i];
          }
        });

        // Update store
        this._applicationContext?.updateLogPreviews(previewMap);

        // Optionally cache to database
        if (this._database && Object.keys(previewMap).length > 0) {
          this._database
            .writeLogPreviews(
              Object.values(previewMap),
              Object.keys(previewMap),
            )
            .catch(() => {});
        }
      },
    );
    this._detailQueue.setOnComplete(
      async (details: LogDetails[], inputs: LogHandle[]) => {
        if (this._database && details.length > 0) {
          for (const [i, detail] of details.entries()) {
            const input = inputs[i];
            if (detail && input) {
              await this._database
                .writeLogDetails(input.name, detail)
                .catch(() => {});
            }
          }
        }
      },
    );
  }

  public startReplication(
    database: DatabaseService,
    api: ClientAPI,
    context: ApplicationContext,
  ) {
    this._database = database;
    this._api = api;
    this._applicationContext = context;
  }

  public stopReplication() {
    this._database = undefined;
    this._api = undefined;
    this._applicationContext = undefined;
  }

  public async sync() {
    if (!this._database) {
      throw new Error("No database available for replication.");
    }

    if (!this._api) {
      throw new Error("No API available for replication.");
    }

    if (!this._applicationContext) {
      throw new Error("No replication context available for replication.");
    }

    // First query the list of logs
    const logFiles = (await this._database.readLogs()) || [];
    let mtime = 0;
    let clientFileCount = 0;
    if (logFiles && logFiles.length > 0) {
      mtime = Math.max(...logFiles.map((file) => file.mtime || 0));
      clientFileCount = logFiles.length;
    }

    // Fetch the updated list of logs from the server
    const updatedLogs = await this._api.get_logs(mtime, clientFileCount);

    // Make a list of the files in current files that are missing
    // from the files we just loaded or which have a lower mtime
    // than the file in the files list.
    const toInvalidate = updatedLogs.filter((current) => {
      const match = logFiles.find((f) => f.name === current.name);
      return (
        !match || (current.mtime && match.mtime && current.mtime < match.mtime)
      );
    });

    // Invalidate summaries and overviews for deleted or updated files
    toInvalidate
      .map((file) => file.name)
      .map((name) => this._database?.clearCacheForFile(name));

    // Cache the current list of files
    await this._database.writeLogs(updatedLogs);

    // Find the selected log (if any)
    const currentLogHandle = this._applicationContext.getSelectedLog();

    // Update the log handles in the application state
    const allLogHandles = (await this._database.readLogs()) || [];
    this._applicationContext?.setLogHandles(allLogHandles);

    // Preserve the current selection
    if (currentLogHandle !== undefined) {
      const newIndex = allLogHandles.findIndex((file) =>
        currentLogHandle.name.endsWith(file.name),
      );

      if (newIndex !== undefined && newIndex !== -1) {
        this._applicationContext.setSelectedLogIndex(newIndex);
      }
    }

    // Schedule any missing previews
    const previewTasks = [...toInvalidate];
    const previews = await this._database.findMissingPreviews(allLogHandles);
    previewTasks.push(...previews);
    this.syncLogPreviews(previewTasks);

    // Schedule preview fetching for new logs
    const detailTasks = [...toInvalidate];
    const details = await this._database.findMissingDetails(allLogHandles);
    detailTasks.push(...details);
    this.syncLogDetails(detailTasks);

    // See if there are any logs without previews and sync them
  }

  syncLogPreviews(logs: LogHandle[]) {
    // Add to queue (deduplicated by name)
    this._previewQueue.enqueue(logs, (log) => log.name);
  }

  syncLogDetails(logs: LogHandle[]) {
    // Add to queue (deduplicated by name)
    this._detailQueue.enqueue(logs, (log) => log.name);
  }
}
