import clsx from "clsx";
import { AgGridReact } from "ag-grid-react";
import { FC, useEffect, useMemo, useRef } from "react";

import { useNavigate } from "react-router-dom";
import { EvalSet } from "../../@types/log";
import { ProgressBar } from "../../components/ProgressBar";
import { useClientEvents } from "../../state/clientEvents";
import { useDocumentTitle, useLogs, useLogsListing } from "../../state/hooks";
import { useStore } from "../../state/store";
import { dirname, isInDirectory } from "../../utils/path";
import { directoryRelativeUrl, join } from "../../utils/uri";
import { ApplicationIcons } from "../appearance/icons";
import { FlowButton } from "../flow/FlowButton";
import { useFlowServerData } from "../flow/hooks";
import { ApplicationNavbar } from "../navbar/ApplicationNavbar";
import { NavbarButton } from "../navbar/NavbarButton";
import { ViewSegmentedControl } from "../navbar/ViewSegmentedControl";
import { logsUrl, useLogRouteParams } from "../routing/url";
import { LogListGrid } from "./grid/LogListGrid";
import { LogListRow } from "./grid/columns/types";
import { FileLogItem, FolderLogItem, PendingTaskItem } from "./LogItem";
import { LogListFooter } from "./LogListFooter";
import styles from "./LogsPanel.module.css";

const rootName = (relativePath: string) => {
  const parts = relativePath.split("/");
  if (parts.length === 0) {
    return "";
  }
  return parts[0];
};

interface LogsPanelProps {
  maybeShowSingleLog?: boolean;
}

export const LogsPanel: FC<LogsPanelProps> = ({ maybeShowSingleLog }) => {
  const { loadLogs } = useLogs();
  const gridRef = useRef<AgGridReact<LogListRow>>(null);

  const logDir = useStore((state) => state.logs.logDir);
  const logFiles = useStore((state) => state.logs.logs);
  const evalSet = useStore((state) => state.logs.evalSet);
  const logPreviews = useStore((state) => state.logs.logPreviews);
  const { filteredCount } = useLogsListing();

  const syncing = useStore((state) => state.app.status.syncing);

  const watchedLogs = useStore((state) => state.logs.listing.watchedLogs);
  const navigate = useNavigate();

  const { logPath } = useLogRouteParams();

  const currentDir = join(logPath || "", logDir);

  useFlowServerData(logPath || "");
  const flowData = useStore((state) => state.logs.flow);

  const { startPolling, stopPolling } = useClientEvents();

  const { setDocumentTitle } = useDocumentTitle();
  useEffect(() => {
    setDocumentTitle({
      logDir: logDir,
    });
  }, [setDocumentTitle, logDir]);

  const previousWatchedLogs = useRef<typeof watchedLogs>(undefined);

  useEffect(() => {
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
      stopPolling();

      if (watchedLogs !== undefined) {
        startPolling(watchedLogs);
      }
      previousWatchedLogs.current = watchedLogs;
    }
  }, [watchedLogs, startPolling, stopPolling]);

  const logItems: Array<FileLogItem | FolderLogItem | PendingTaskItem> =
    useMemo(() => {
      const logItems: Array<FileLogItem | FolderLogItem | PendingTaskItem> = [];

      const processedFolders = new Set<string>();
      const existingLogTaskIds = new Set<string>();

      for (const logFile of logFiles) {
        if (logFile.task_id) {
          existingLogTaskIds.add(logFile.task_id);
        }

        const name = logFile.name;

        const cleanDir = currentDir.endsWith("/")
          ? currentDir.slice(0, -1)
          : currentDir;

        const dirWithSlash = !currentDir.endsWith("/")
          ? currentDir + "/"
          : currentDir;

        if (isInDirectory(name, cleanDir)) {
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
            url: logsUrl(path, logDir),
            log: logFile,
            logPreview: logPreviews[logFile.name],
          });
        } else if (name.startsWith(dirWithSlash)) {
          const relativePath = directoryRelativeUrl(name, currentDir);

          const dirName = decodeURIComponent(rootName(relativePath));
          const currentDirRelative = directoryRelativeUrl(currentDir, logDir);
          const url = join(dirName, decodeURIComponent(currentDirRelative));
          if (!processedFolders.has(dirName)) {
            logItems.push({
              id: dirName,
              name: dirName,
              type: "folder",
              url: logsUrl(url, logDir),
              itemCount: logFiles.filter((file) =>
                file.name.startsWith(dirname(name)),
              ).length,
            });
            processedFolders.add(dirName);
          }
        }
      }

      // Restore prior behavior: folders first, then files (both alphabetical)
      logItems.sort((a, b) => {
        const rank = (t: string) => (t === "folder" ? 0 : t === "file" ? 1 : 2);
        const r = rank(a.type) - rank(b.type);
        if (r !== 0) return r;
        return a.name.localeCompare(b.name);
      });

      const collapsedLogItems: Array<
        FileLogItem | FolderLogItem | PendingTaskItem
      > = collapseLogItems(evalSet, logItems);

      const withPending = appendPendingItems(
        evalSet,
        existingLogTaskIds,
        collapsedLogItems,
      );

      // Assign display index to non-folder rows only
      let displayIndex = 1;
      const numbered = withPending.map((item) => {
        if (item.type === "folder") {
          return item;
        }
        return { ...item, displayIndex: displayIndex++ };
      });

      return numbered;
    }, [evalSet, logFiles, currentDir, logDir, logPreviews]);

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

  const handleResetFilters = () => {
    if (gridRef.current?.api) {
      gridRef.current.api.setFilterModel(null);
    }
  };

  const filterModel = gridRef.current?.api?.getFilterModel() || {};
  const hasFilter = Object.keys(filterModel).length > 0;

  useEffect(() => {
    if (maybeShowSingleLog && logItems.length === 1) {
      const onlyItem = logItems[0];
      if (onlyItem.url) {
        navigate(onlyItem.url);
      }
    }
  }, [logItems, maybeShowSingleLog, navigate]);

  return (
    <div className={clsx(styles.panel)}>
      <ApplicationNavbar
        fnNavigationUrl={logsUrl}
        currentPath={logPath}
        showActivity="log"
      >
        {hasFilter && (
          <NavbarButton
            key="reset-filters"
            label="Reset Filters"
            icon={ApplicationIcons.filter}
            onClick={handleResetFilters}
          />
        )}
        <ViewSegmentedControl selectedSegment="logs" />
        {flowData && <FlowButton />}
      </ApplicationNavbar>

      <>
        <div className={clsx(styles.list, "text-size-smaller")}>
          <LogListGrid
            items={logItems}
            currentPath={currentDir}
            gridRef={gridRef}
          />
        </div>
        <LogListFooter
          itemCount={logItems.length}
          filteredCount={filteredCount}
          progressText={syncing ? "Syncing data" : undefined}
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
      </>
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

  const running = logItems.some(
    (l) => l.type === "file" && l.logPreview?.status === "started",
  );
  if (!running) {
    return logItems;
  }

  const taskIdToItems = new Map<string, FileLogItem[]>();
  const itemsWithoutTaskId: Array<FolderLogItem | FileLogItem> = [];

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

  const selectedItems = new Map<string, FileLogItem>();
  for (const [taskId, items] of taskIdToItems) {
    let bestItem = items[0];
    for (const item of items) {
      const currentStatus = item.logPreview?.status;
      const currentMtime = item.log.mtime ?? 0;
      const bestStatus = bestItem.logPreview?.status;
      const bestMtime = bestItem.log.mtime ?? 0;

      if (currentStatus === "started" && bestStatus !== "started") {
        bestItem = item;
      } else if (currentStatus === "success" && bestStatus === "error") {
        bestItem = item;
      } else if (currentStatus === bestStatus && currentMtime > bestMtime) {
        bestItem = item;
      }
    }
    selectedItems.set(taskId, bestItem);
  }

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

  pendingTasks.sort((a, b) => a.name.localeCompare(b.name));

  collapsedLogItems.push(...pendingTasks);

  return collapsedLogItems;
};
