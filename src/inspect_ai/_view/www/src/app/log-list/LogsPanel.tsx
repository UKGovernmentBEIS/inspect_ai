import clsx from "clsx";
import { FC, useEffect, useMemo, useRef } from "react";

import { ProgressBar } from "../../components/ProgressBar";
import { useClientEvents } from "../../state/clientEvents";
import { useLogs } from "../../state/hooks";
import { useUnloadLog } from "../../state/log";
import { useStore } from "../../state/store";
import { dirname, isInDirectory } from "../../utils/path";
import { directoryRelativeUrl, join } from "../../utils/uri";
import { Navbar } from "../navbar/Navbar";
import { logUrl, useLogRouteParams } from "../routing/url";
import { LogListGrid } from "./grid/LogListGrid";
import { FileLogItem, FolderLogItem } from "./LogItem";
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

interface LogsPanelProps {}

export const LogsPanel: FC<LogsPanelProps> = () => {
  // Get the logs from the store
  const loading = useStore((state) => state.app.status.loading);

  const { loadLogs } = useLogs();
  const logs = useStore((state) => state.logs.logs);
  const logHeaders = useStore((state) => state.logs.logOverviews);
  const headersLoading = useStore((state) => state.logs.logOverviewsLoading);
  const watchedLogs = useStore((state) => state.logs.listing.watchedLogs);

  // Unload the load when this is mounted. This prevents the old log
  // data from being displayed when navigating back to the logs panel
  // and also ensures that we reload logs when freshly navigating to them.
  const { unloadLog } = useUnloadLog();
  useEffect(() => {
    unloadLog();
  }, []);

  const { logPath } = useLogRouteParams();

  const currentDir = join(logPath || "", logs.log_dir);

  // Polling for client events
  const { startPolling, stopPolling } = useClientEvents();

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

  // All the items visible in the current directory (might span
  // multiple pages)
  const logItems: Array<FileLogItem | FolderLogItem> = useMemo(() => {
    // Build the list of files / folders that for the current directory
    const logItems: Array<FileLogItem | FolderLogItem> = [];

    // Track process folders to avoid duplicates
    const processedFolders = new Set<string>();

    for (const logFile of logs.files) {
      // The file name
      const name = logFile.name;

      // Process paths in the current directory
      const cleanDir = currentDir.endsWith("/")
        ? currentDir.slice(0, -1)
        : currentDir;

      if (isInDirectory(logFile.name, cleanDir)) {
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
      } else if (name.startsWith(currentDir)) {
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

    return logItems;
  }, [logPath, logs.files, logHeaders]);

  useEffect(() => {
    const exec = async () => {
      await loadLogs();
    };
    exec();
  }, [loadLogs]);

  return (
    <div className={clsx(styles.panel)}>
      <Navbar>
        <LogsFilterInput />
      </Navbar>

      <ProgressBar animating={loading || headersLoading} />
      <div className={clsx(styles.list, "text-size-smaller")}>
        <LogListGrid items={logItems} />
      </div>
      <LogListFooter
        logDir={currentDir}
        itemCount={logItems.length}
        progressText={
          loading ? "Loading logs" : headersLoading ? "Loading data" : undefined
        }
      />
    </div>
  );
};
