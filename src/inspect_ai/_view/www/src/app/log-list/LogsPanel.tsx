import clsx from "clsx";
import { FC, useEffect, useMemo } from "react";

import { useParams } from "react-router-dom";
import { EvalLogHeader } from "../../client/api/types";
import { ProgressBar } from "../../components/ProgressBar";
import { useLogs, usePagination } from "../../state/hooks";
import { useStore } from "../../state/store";
import { dirname, isInDirectory } from "../../utils/path";
import { directoryRelativeUrl, join } from "../../utils/uri";
import { Navbar } from "../navbar/Navbar";
import { logUrl } from "../routing/url";
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
export const kDefaultPageSize = 40;

interface LogsPanelProps {}

export const LogsPanel: FC<LogsPanelProps> = () => {
  // Get the logs from the store
  const loading = useStore((state) => state.app.status.loading);

  const { loadLogs } = useLogs();
  const logs = useStore((state) => state.logs.logs);

  const loadHeaders = useStore((state) => state.logsActions.loadHeaders);
  const logHeaders = useStore((state) => state.logs.logHeaders);
  const updateLogHeaders = useStore(
    (state) => state.logsActions.updateLogHeaders,
  );

  // Items that are in the current page
  const { page, itemsPerPage } = usePagination(
    kLogsPaginationId,
    kDefaultPageSize,
  );

  const { logPath } = useParams<{
    logPath?: string;
    tabId?: string;
    sampleId?: string;
    epoch?: string;
  }>();

  const currentDir = join(decodeURIComponent(logPath || ""), logs.log_dir);

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

        if (!processedFolders.has(dirName)) {
          logItems.push({
            id: dirName,
            name: dirName,
            type: "folder",
            url: logUrl(dirName, logs.log_dir),
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
    const fileItems = pageItems.filter((item) => item.type === "file");
    const logFiles = fileItems
      .map((item) => item.logFile)
      .filter((file) => file !== undefined)
      .filter((logFile) => {
        // Filter out files that are already loaded
        return logHeaders[logFile.name] === undefined;
      });

    const exec = async () => {
      const headers = await loadHeaders(logFiles);
      if (headers) {
        const updatedHeaders: Record<string, EvalLogHeader> = {};

        headers.forEach((header, index) => {
          const logFile = logFiles[index];
          updatedHeaders[logFile.name] = header as EvalLogHeader;
        });
        updateLogHeaders(updatedHeaders);
      }
    };
    exec();
  }, [pageItems]);

  return (
    <div className={clsx(styles.panel)}>
      <Navbar />
      <ProgressBar animating={loading} />
      <div className={clsx(styles.list, "text-size-smaller")}>
        <LogListGrid items={logItems} />
      </div>
      <LogListFooter
        logDir={currentDir}
        itemCount={logItems.length}
        running={loading}
      />
    </div>
  );
};
