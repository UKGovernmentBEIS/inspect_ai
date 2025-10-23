import clsx from "clsx";
import { FC, KeyboardEvent, useEffect, useMemo, useRef } from "react";

import { useNavigate } from "react-router-dom";
import { EvalSet } from "../../@types/log";
import { ActivityBar } from "../../components/ActivityBar";
import { ProgressBar } from "../../components/ProgressBar";
import { useClientEvents } from "../../state/clientEvents";
import { useDocumentTitle, useLogs, usePagination } from "../../state/hooks";
import { useStore } from "../../state/store";
import { dirname, isInDirectory } from "../../utils/path";
import { directoryRelativeUrl, join } from "../../utils/uri";
import { Navbar } from "../navbar/Navbar";
import { logUrl, useLogRouteParams } from "../routing/url";
import { LogListGrid, LogListGridHandle } from "./grid/LogListGrid";
import { FileLogItem, FolderLogItem, PendingTaskItem } from "./LogItem";
import { LogListFooter } from "./LogListFooter";
import { LogsFilterInput } from "./LogsFilterInput";
import styles from "./LogsPanel.module.css";
import { ViewerOptionsButton } from "./ViewerOptionsButton";
import { ViewerOptionsPopover } from "./ViewerOptionsPopover";

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
  const logDir = useStore((state) => state.logs.logDir);
  const logFiles = useStore((state) => state.logs.logs);
  const evalSet = useStore((state) => state.logs.evalSet);
  const logHeaders = useStore((state) => state.logs.logOverviews);
  const headersLoading = useStore((state) => state.logs.logOverviewsLoading);
  const watchedLogs = useStore((state) => state.logs.listing.watchedLogs);
  const navigate = useNavigate();

  const { setPage } = usePagination(kLogsPaginationId, kDefaultPageSize);

  const filterRef = useRef<HTMLInputElement>(null);
  const gridRef = useRef<LogListGridHandle>(null);
  const optionsRef = useRef<HTMLButtonElement>(null);

  const isShowing = useStore((state) => state.app.dialogs.options);
  const setShowing = useStore(
    (state) => state.appActions.setShowingOptionsDialog,
  );

  const { logPath } = useLogRouteParams();

  const currentDir = join(logPath || "", logDir);

  // Polling for client events
  const { startPolling, stopPolling } = useClientEvents();

  const { setDocumentTitle } = useDocumentTitle();
  useEffect(() => {
    setDocumentTitle({
      logDir: logDir,
    });
  }, [setDocumentTitle, logDir]);

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
  const logItems: Array<FileLogItem | FolderLogItem | PendingTaskItem> =
    useMemo(() => {
      // Build the list of files / folders that for the current directory
      const logItems: Array<FileLogItem | FolderLogItem | PendingTaskItem> = [];

      // Track process folders to avoid duplicates
      const processedFolders = new Set<string>();
      const existingLogTaskIds = new Set<string>();

      for (const logFile of logFiles) {
        // Note that this task is running or complete
        if (logFile.task_id) {
          existingLogTaskIds.add(logFile.task_id);
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
          const dirName = directoryRelativeUrl(currentDir, logDir);
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
            url: logUrl(path, logDir),
            log: logFile,
            logPreview: logHeaders[logFile.name],
          });
        } else if (name.startsWith(dirWithSlash)) {
          // This is file that is next level (or deeper) child
          // of the current directory, extract the top level folder name

          const relativePath = directoryRelativeUrl(name, currentDir);

          const dirName = decodeURIComponent(rootName(relativePath));
          const currentDirRelative = directoryRelativeUrl(currentDir, logDir);
          const url = join(dirName, decodeURIComponent(currentDirRelative));
          if (!processedFolders.has(dirName)) {
            logItems.push({
              id: dirName,
              name: dirName,
              type: "folder",
              url: logUrl(url, logDir),
              itemCount: logFiles.filter((file) =>
                file.name.startsWith(dirname(name)),
              ).length,
            });
            processedFolders.add(dirName);
          }
        }
      }

      // Ensure there is only one entry for each task id, preferring to
      // always show running or complete tasks (over error tasks). Ensure that the
      // order of all items isn't changed
      const collapsedLogItems: Array<
        FileLogItem | FolderLogItem | PendingTaskItem
      > = collapseLogItems(evalSet, logItems);

      return appendPendingItems(evalSet, existingLogTaskIds, collapsedLogItems);
    }, [logPath, logFiles, logHeaders, evalSet]);

  const progress = useMemo(() => {
    let pending = 0;
    let total = 0;
    for (const item of logItems) {
      if (item.type === "file" || item.type === "pending-task") {
        total += 1;
        if (
          item.type === "pending-task" ||
          item.logPreview?.status === "started"
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
    } else if (
      e.key === "Escape" &&
      document.activeElement === filterRef.current
    ) {
      e.preventDefault();
      gridRef.current?.focus();
    }
  }

  return (
    <div
      className={clsx(styles.panel)}
      onKeyDown={(e) => {
        handleKeyDown(e);
      }}
    >
      <Navbar>
        <LogsFilterInput ref={filterRef} />
        <ViewerOptionsButton
          showing={isShowing}
          setShowing={setShowing}
          ref={optionsRef}
        />
        <ViewerOptionsPopover
          positionEl={optionsRef.current}
          showing={isShowing}
          setShowing={setShowing}
        />
      </Navbar>

      <ActivityBar animating={loading || headersLoading} />
      <div className={clsx(styles.list, "text-size-smaller")}>
        <LogListGrid ref={gridRef} items={logItems} />
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

export const collapseLogItems = (
  evalSet: EvalSet | undefined,
  logItems: (FileLogItem | FolderLogItem | PendingTaskItem)[],
): (FileLogItem | FolderLogItem | PendingTaskItem)[] => {
  if (!evalSet) {
    return logItems;
  }

  const taskIdToItems = new Map<string, FileLogItem[]>();
  const itemsWithoutTaskId: Array<FolderLogItem | FileLogItem> = [];

  // Group file items by task_id
  for (const item of logItems) {
    if (item.type === "file" && item.log.task_id) {
      const taskId = item.log.task_id;
      if (!taskIdToItems.has(taskId)) {
        taskIdToItems.set(taskId, []);
      }
      taskIdToItems.get(taskId)!.push(item);
    } else if (item.type === "folder" || item.type === "file") {
      itemsWithoutTaskId.push(item);
    }
  }

  // For each task_id, select the best item (prefer running/complete over error)
  const selectedItems = new Map<string, FileLogItem>();
  for (const [taskId, items] of taskIdToItems) {
    // Sort by status priority: started > success > error
    // If same priority, take the last one
    let bestItem = items[0];
    for (const item of items) {
      const currentStatus = item.logOverview?.status;
      const bestStatus = bestItem.logOverview?.status;

      // Prefer started over everything
      if (currentStatus === "started" && bestStatus !== "started") {
        bestItem = item;
      }

      // Prefer success over error
      else if (currentStatus === "success" && bestStatus === "error") {
        bestItem = item;
      }

      // If same status or current is error, prefer the last one (most recent)
      else if (currentStatus === bestStatus) {
        bestItem = item;
      }
    }
    selectedItems.set(taskId, bestItem);
  }

  // Rebuild logItems maintaining order, replacing duplicates with selected item
  const collapsedLogItems: Array<
    FileLogItem | FolderLogItem | PendingTaskItem
  > = [];
  const processedTaskIds = new Set<string>();

  for (const item of logItems) {
    if (item.type === "file" && item.log.task_id) {
      const taskId = item.log.task_id;
      if (!processedTaskIds.has(taskId)) {
        const selectedItem = selectedItems.get(taskId);
        if (selectedItem) {
          collapsedLogItems.push(selectedItem);
        }
        processedTaskIds.add(taskId);
      }
    } else {
      // Include folders and files without task_id
      collapsedLogItems.push(item);
    }
  }
  return collapsedLogItems;
};

const appendPendingItems = (
  evalSet: EvalSet | undefined,
  tasksWithLogFiles: Set<string>,
  collapsedLogItems: (FileLogItem | FolderLogItem | PendingTaskItem)[],
): (FileLogItem | FolderLogItem | PendingTaskItem)[] => {
  const pendingTasks = new Array<PendingTaskItem>();
  for (const task of evalSet?.tasks || []) {
    if (!tasksWithLogFiles.has(task.task_id)) {
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
  collapsedLogItems.push(...pendingTasks);

  return collapsedLogItems;
};
