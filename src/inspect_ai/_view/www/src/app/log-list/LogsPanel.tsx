import clsx from "clsx";
import { FC, useEffect, useMemo } from "react";

import { ProgressBar } from "../../components/ProgressBar";
import { useLogs, usePagination } from "../../state/hooks";
import { useStore } from "../../state/store";
import { dirname, isInDirectory } from "../../utils/path";
import { directoryRelativeUrl, join } from "../../utils/uri";
import { Navbar } from "../navbar/Navbar";
import { logUrl, useDecodedParams } from "../routing/url";
import { LogListGrid } from "./grid/LogListGrid";
import { FileLogItem, FolderLogItem } from "./LogItem";
import { LogListFooter } from "./LogListFooter";
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

  const { loadLogs, loadHeaders } = useLogs();
  const logs = useStore((state) => state.logs.logs);
  const logHeaders = useStore((state) => state.logs.logHeaders);
  const headersLoading = useStore((state) => state.logs.headersLoading);

  // Items that are in the current page
  const { page, itemsPerPage } = usePagination(
    kLogsPaginationId,
    kDefaultPageSize,
  );

  const { logPath } = useDecodedParams<{
    logPath?: string;
    tabId?: string;
    sampleId?: string;
    epoch?: string;
  }>();

  const currentDir = join(logPath || "", logs.log_dir);

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
  }, [logPath, logs.files]);

  useEffect(() => {
    const exec = async () => {
      await loadLogs();
    };
    exec();
  }, [loadLogs]);

  const pageItems = useMemo(() => {
    const start = (page || 0) * itemsPerPage;
    const end = start + itemsPerPage;
    return logItems.slice(start, end);
  }, [logItems, page, itemsPerPage]);

  // Load headers for any files that are not yet loaded
  useEffect(() => {
    const exec = async () => {
      const fileItems = pageItems.filter((item) => item.type === "file");
      const logFiles = fileItems
        .map((item) => item.logFile)
        .filter((file) => file !== undefined)
        .filter((logFile) => {
          // Filter out files that are already loaded
          return logHeaders[logFile.name] === undefined;
        });

      if (logFiles.length > 0) {
        await loadHeaders(logFiles);
      }
    };
    exec();
  }, [pageItems, loadHeaders, logHeaders]);

  return (
    <div className={clsx(styles.panel)}>
      <Navbar />
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
