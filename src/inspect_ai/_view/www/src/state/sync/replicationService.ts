import {
  ClientAPI,
  LogDetails,
  LogHandle,
  LogPreview,
} from "../../client/api/types";
import { DatabaseService } from "../../client/database";
import { WorkPriority, WorkQueue } from "../../utils/workQueue";

export interface ApplicationContext {
  setLogHandles: (logs: LogHandle[]) => void;
  getSelectedLog: () => LogHandle | undefined;
  setSelectedLogIndex: (index: number) => void;
  updateLogPreviews: (previews: Record<string, LogPreview>) => void;
  setLoading: (loading: boolean) => void;
  setBackgroundSyncing: (syncing: boolean) => void;
  setDbStats: (stats: {
    logCount: number;
    previewCount: number;
    detailsCount: number;
  }) => void;
}

export class ReplicationService {
  private _database: DatabaseService | undefined = undefined;
  private _api: ClientAPI | undefined = undefined;
  private _applicationContext: ApplicationContext | undefined = undefined;
  private _previewQueue: WorkQueue<LogHandle, LogPreview>;
  private _detailQueue: WorkQueue<LogHandle, LogDetails>;
  private _processingCount: number;
  private _pendingSync: Promise<LogHandle[]> | null = null;
  private _syncQueued: boolean = false;

  constructor() {
    this._previewQueue = new WorkQueue<LogHandle, LogPreview>({
      batchSize: 10,
      processingDelay: 100,
      onProcessingChanged: this.processingChanged,
    });
    this._detailQueue = new WorkQueue<LogHandle, LogDetails>({
      batchSize: 3,
      processingDelay: 50,
      onProcessingChanged: this.processingChanged,
    });
    this._processingCount = 0;

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
          this.updateDbStats();
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
              this.updateDbStats();
            }
          }
        }
      },
    );
  }

  processingChanged = (processing: boolean) => {
    this._processingCount += processing ? 1 : -1;
    if (this._processingCount > 0) {
      this._applicationContext?.setBackgroundSyncing(true);
    } else {
      this._applicationContext?.setBackgroundSyncing(false);
    }
  };

  private updateDbStats() {
    if (!this._database || !this._applicationContext) return;

    Promise.all([
      this._database.countRows("logs"),
      this._database.countRows("logPreviews"),
      this._database.countRows("logDetails"),
    ])
      .then(([logCount, previewCount, detailsCount]) => {
        this._applicationContext?.setDbStats({
          logCount,
          previewCount,
          detailsCount,
        });
      })
      .catch(() => {});
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

  public async sync(progress?: boolean): Promise<LogHandle[]> {
    // If sync is running and another is already queued, just wait for the queued one
    if (this._pendingSync && this._syncQueued) {
      return this._pendingSync;
    }

    // If sync is running but none queued, queue this one
    if (this._pendingSync) {
      this._syncQueued = true;
      await this._pendingSync;
      this._syncQueued = false;
      // After pending completes, run one more sync
      return this.sync(progress);
    }

    // No sync running, execute immediately
    this._pendingSync = this._syncImpl(progress);

    try {
      return await this._pendingSync;
    } finally {
      this._pendingSync = null;
    }
  }

  private async _syncImpl(progress?: boolean): Promise<LogHandle[]> {
    if (!this._database) {
      throw new Error("No database available for replication.");
    }

    if (!this._api) {
      throw new Error("No API available for replication.");
    }

    if (!this._applicationContext) {
      throw new Error("No replication context available for replication.");
    }

    if (progress) {
      this._applicationContext.setLoading(true);
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
    const response = await this._api.get_logs(mtime, clientFileCount);
    const updatedLogs = response.files;

    // Find deleted file
    if (response.response_type === "full") {
      const deletedFiles = logFiles.filter((current) => {
        return !updatedLogs.find((f) => f.name === current.name);
      });
      for (const file of deletedFiles) {
        this._database?.clearCacheForFile(file.name);
      }
    }

    // Make a list of the files in current files that are missing
    // from the files we just loaded or which have a lower mtime
    // than the file in the files list.
    const toInvalidate = updatedLogs.filter((remoteLog) => {
      const localCopy = logFiles.find((f) => f.name === remoteLog.name);

      // There isn't a local copy, so it's new
      if (!localCopy) {
        return true;
      }

      // If there is a local copy, but the remote mtime is newer, invalidate
      if (remoteLog.mtime && localCopy.mtime) {
        return remoteLog.mtime > localCopy.mtime;
      }

      // times are missing, so assume it's changed
      return true;
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
    for (const p of previews) {
      if (!previewTasks.find((t) => t.name === p.name)) {
        previewTasks.push(p);
      }
    }
    this.queueLogPreviews(previewTasks);

    // Schedule preview fetching for new logs
    const detailTasks = [...toInvalidate];
    const details = await this._database.findMissingDetails(allLogHandles);
    for (const d of details) {
      if (!detailTasks.find((t) => t.name === d.name)) {
        detailTasks.push(d);
      }
    }
    this.queueLogDetails(detailTasks);

    if (progress) {
      this._applicationContext.setLoading(false);
    }

    return allLogHandles;
  }

  public async loadLogPreviews(context: {
    logs?: LogHandle[];
    force?: boolean;
  }) {
    this._applicationContext?.setLoading(true);
    try {
      if (context.force) {
        const toLoad = context.logs || (await this._database?.readLogs()) || [];
        await this._previewQueue.atOnce(toLoad);
      } else {
        const allLogs = (await this._database?.readLogs()) || [];
        const loaded = (await this._database?.readLogPreviews(allLogs)) || {};

        const logList = context.logs || allLogs;
        const filtered = logList.filter((log) => {
          const loadedPreview = loaded[log.name];
          if (!loadedPreview) {
            return true;
          }

          if (loadedPreview.status === "success") {
            return false;
          }
          return true;
        });

        // Activate existing previews
        if (Object.keys(loaded).length > 0) {
          this._applicationContext?.updateLogPreviews(loaded);
        }

        // Queue any missing previews
        if (filtered.length > 0) {
          await this._previewQueue.atOnce(filtered);
        }
      }
    } finally {
      this._applicationContext?.setLoading(false);
    }
  }

  queueLogPreviews(
    logs: LogHandle[],
    priority: WorkPriority = WorkPriority.Medium,
  ) {
    // Add to queue (deduplicated by name)
    this._previewQueue.enqueue(logs, (log) => log.name, priority);
  }

  private count = 0;
  queueLogDetails(
    logs: LogHandle[],
    priority: WorkPriority = WorkPriority.Medium,
  ) {
    this.count = this.count + logs.length;
    // Add to queue (deduplicated by name)
    this._detailQueue.enqueue(logs, (log) => log.name, priority);
  }
}
