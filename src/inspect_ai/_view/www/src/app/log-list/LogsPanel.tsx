import clsx from "clsx";
import { FC, KeyboardEvent, useEffect, useMemo, useRef } from "react";

import { useNavigate } from "react-router-dom";
import { ActivityBar } from "../../components/ActivityBar";
import { ProgressBar } from "../../components/ProgressBar";
import { useClientEvents } from "../../state/clientEvents";
import { useDocumentTitle, useLogs, usePagination } from "../../state/hooks";
import { useStore } from "../../state/store";
import { dirname, isInDirectory } from "../../utils/path";
import { directoryRelativeUrl, join } from "../../utils/uri";
import { Navbar } from "../navbar/Navbar";
import { logUrl, useLogRouteParams } from "../routing/url";
import { LogListGrid } from "./grid/LogListGrid";
import { FileLogItem, FolderLogItem, PendingTaskItem } from "./LogItem";
import { LogListFooter } from "./LogListFooter";
import { LogsFilterInput } from "./LogsFilterInput";
import styles from "./LogsPanel.module.css";

const rootName = (relativePath: string) => {
  const parts = relativePath.split("/");
  if (parts.length === 0) {
    return "";
  }
  return parts[0];
};

export const kLogsPaginationId = "logs-list-pagination";
export const kDefaultPageSize = 30;

interface LogsPanelProps {
  maybeShowSingleLog?: boolean;
}

export const LogsPanel: FC<LogsPanelProps> = ({ maybeShowSingleLog }) => {
  // Get the logs from the store
  const loading = useStore((state) => state.app.status.loading);

  const { loadLogs } = useLogs();
  const logs = useStore((state) => state.logs.logs);
  const evalSet = useStore((state) => state.logs.evalSet);
  const logHeaders = useStore((state) => state.logs.logOverviews);
  const headersLoading = useStore((state) => state.logs.logOverviewsLoading);
  const watchedLogs = useStore((state) => state.logs.listing.watchedLogs);
  const navigate = useNavigate();

  const { setPage } = usePagination(kLogsPaginationId, kDefaultPageSize);

  const filterRef = useRef<HTMLInputElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const { logPath } = useLogRouteParams();

  const currentDir = join(logPath || "", logs.log_dir);

  // Polling for client events
  const { startPolling, stopPolling } = useClientEvents();

  const { setDocumentTitle } = useDocumentTitle();
  useEffect(() => {
    setDocumentTitle({
      logDir: logs.log_dir,
    });
  }, [setDocumentTitle, logs.log_dir]);

  const previousWatchedLogs = useRef<typeof watchedLogs>(undefined);

  useEffect(() => {
    // Only restart polling if the watched logs have actually changed
    const current =
      watchedLogs
        ?.map((log) => log.name)
        .sort()
        .join(",") || "";
    const previous =
      previousWatchedLogs.current === undefined
        ? undefined
        : previousWatchedLogs.current
            ?.map((log) => log.name)
            .sort()
            .join(",") || "";

    if (current !== previous) {
      // Always stop current polling first when logs change
      stopPolling();

      if (watchedLogs !== undefined) {
        startPolling(watchedLogs);
      }
      previousWatchedLogs.current = watchedLogs;
    }
  }, [watchedLogs]);

  // Focus the panel when it loads
  useEffect(() => {
    setTimeout(() => {
      rootRef.current?.focus();
    }, 10);
  }, []);

  // All the items visible in the current directory (might span
  // multiple pages)
  const logItems: Array<FileLogItem | FolderLogItem | PendingTaskItem> =
    useMemo(() => {
      // Build the list of files / folders that for the current directory
      const logItems: Array<FileLogItem | FolderLogItem | PendingTaskItem> = [];

      // Track process folders to avoid duplicates
      const processedFolders = new Set<string>();
      const runningOrFinishedTasks = new Set<string>();

      for (const logFile of logs.files) {
        // Note that this task is running or complete
        if (logFile.task_id) {
          runningOrFinishedTasks.add(logFile.task_id);
        }

        // The file name
        const name = logFile.name;

        // Process paths in the current directory
        const cleanDir = currentDir.endsWith("/")
          ? currentDir.slice(0, -1)
          : currentDir;

        const dirWithSlash = !currentDir.endsWith("/")
          ? currentDir + "/"
          : currentDir;

        if (isInDirectory(name, cleanDir)) {
          // This is a file within the current directory
          const dirName = directoryRelativeUrl(currentDir, logs.log_dir);
          const relativePath = directoryRelativeUrl(name, currentDir);

          const fileOrFolderName = decodeURIComponent(rootName(relativePath));
          const path = join(
            decodeURIComponent(relativePath),
            decodeURIComponent(dirName),
          );

          logItems.push({
            id: fileOrFolderName,
            name: fileOrFolderName,
            type: "file",
            url: logUrl(path, logs.log_dir),
            logFile: logFile,
            logOverview: logHeaders[logFile.name],
          });
        } else if (name.startsWith(dirWithSlash)) {
          // This is file that is next level (or deeper) child
          // of the current directory, extract the top level folder name

          const relativePath = directoryRelativeUrl(name, currentDir);

          const dirName = decodeURIComponent(rootName(relativePath));
          const currentDirRelative = directoryRelativeUrl(
            currentDir,
            logs.log_dir,
          );
          const url = join(dirName, decodeURIComponent(currentDirRelative));
          if (!processedFolders.has(dirName)) {
            logItems.push({
              id: dirName,
              name: dirName,
              type: "folder",
              url: logUrl(url, logs.log_dir),
              itemCount: logs.files.filter((file) =>
                file.name.startsWith(dirname(name)),
              ).length,
            });
            processedFolders.add(dirName);
          }
        }
      }

      const pendingTasks = new Array<PendingTaskItem>();
      for (const task of evalSet?.tasks || []) {
        if (!runningOrFinishedTasks.has(task.task_id)) {
          pendingTasks.push({
            id: task.task_id,
            name: task.name || "<unknown>",
            model: task.model,
            type: "pending-task",
          });
        }
      }

      // Sort pending tasks by name
      pendingTasks.sort((a, b) => a.name.localeCompare(b.name));

      // Add pending tasks to the end of the list
      logItems.push(...pendingTasks);

      return logItems;
    }, [logPath, logs.files, logHeaders, evalSet]);

  const progress = useMemo(() => {
    let pending = 0;
    let total = 0;
    for (const item of logItems) {
      if (item.type === "file" || item.type === "pending-task") {
        total += 1;
        if (
          item.type === "pending-task" ||
          item.logOverview?.status === "started"
        ) {
          pending += 1;
        }
      }
    }
    return {
      complete: total - pending,
      total,
    };
  }, [logItems]);

  useEffect(() => {
    const exec = async () => {
      await loadLogs(logPath);
    };
    exec();
  }, [loadLogs, logPath]);

  useEffect(() => {
    setPage(0);
  }, [currentDir]);

  useEffect(() => {
    if (maybeShowSingleLog && logItems.length === 1) {
      const onlyItem = logItems[0];
      if (onlyItem.url) {
        navigate(onlyItem.url);
      }
    }
  }, [logItems, maybeShowSingleLog]);

  function handleKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === "f" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      filterRef.current?.focus();
    }
  }

  return (
    <div
      ref={rootRef}
      className={clsx(styles.panel)}
      onKeyDown={(e) => {
        handleKeyDown(e);
      }}
      tabIndex={0}
    >
      <Navbar>
        <LogsFilterInput ref={filterRef} />
      </Navbar>

      <ActivityBar animating={loading || headersLoading} />
      <div className={clsx(styles.list, "text-size-smaller")}>
        <LogListGrid items={logItems} />
      </div>
      <LogListFooter
        logDir={currentDir}
        itemCount={logItems.length}
        progressText={
          loading ? "Loading logs" : headersLoading ? "Loading data" : undefined
        }
        progressBar={
          progress.total !== progress.complete ? (
            <ProgressBar
              min={0}
              max={progress.total}
              value={progress.complete}
              width="100px"
            />
          ) : undefined
        }
      />
    </div>
  );
};
