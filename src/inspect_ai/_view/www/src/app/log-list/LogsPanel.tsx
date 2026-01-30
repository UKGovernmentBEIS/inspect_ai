import clsx from "clsx";
import { AgGridReact } from "ag-grid-react";
import { FC, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useNavigate } from "react-router-dom";
import { EvalSet } from "../../@types/log";
import { ProgressBar } from "../../components/ProgressBar";
import { useClientEvents } from "../../state/clientEvents";
import {
  useDocumentTitle,
  useLogs,
  useLogsListing,
  useLogsWithretried,
} from "../../state/hooks";
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
import { ColumnSelectorPopover } from "../shared/ColumnSelectorPopover";
import { useLogListColumns } from "./grid/columns/hooks";
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
  const [showColumnSelector, setShowColumnSelector] = useState(false);
  const columnButtonRef = useRef<HTMLButtonElement>(null);

  const showRetriedLogs = useStore((state) => state.logs.showRetriedLogs);
  const setShowRetriedLogs = useStore(
    (state) => state.logsActions.setShowRetriedLogs,
  );
  const logDir = useStore((state) => state.logs.logDir);
  const logFiles = useLogsWithretried();
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
  }, [watchedLogs, startPolling, stopPolling]);

  const [logItems, hasRetriedLogs]: [
    Array<FileLogItem | FolderLogItem | PendingTaskItem>,
    boolean,
  ] = useMemo(() => {
    const folderItems: Array<FileLogItem | FolderLogItem | PendingTaskItem> =
      [];
    const fileItems: Array<FileLogItem | FolderLogItem | PendingTaskItem> = [];

    // Track processed folders to avoid duplicates
    const processedFolders = new Set<string>();
    const existingLogTaskIds = new Set<string>();
    let _hasRetriedLogs = false;

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

        if (logFile.retried) {
          _hasRetriedLogs = true;
        }

        if (showRetriedLogs || !logFile.retried) {
          fileItems.push({
            id: fileOrFolderName,
            name: fileOrFolderName,
            type: "file",
            url: logsUrl(path, logDir),
            log: logFile,
            logPreview: logPreviews[logFile.name],
          });
        }
      } else if (name.startsWith(dirWithSlash)) {
        // This is file that is next level (or deeper) child of the current directory
        const relativePath = directoryRelativeUrl(name, currentDir);

        const dirName = decodeURIComponent(rootName(relativePath));
        const currentDirRelative = directoryRelativeUrl(currentDir, logDir);
        const url = join(dirName, decodeURIComponent(currentDirRelative));
        if (!processedFolders.has(dirName)) {
          folderItems.push({
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

    const orderedItems = [...folderItems, ...fileItems];

    const _logFiles = appendPendingItems(
      evalSet,
      existingLogTaskIds,
      orderedItems,
    );

    return [_logFiles, _hasRetriedLogs];
  }, [evalSet, logFiles, currentDir, logDir, logPreviews, showRetriedLogs]);

  const { columns, setColumnVisibility } = useLogListColumns();

  // Wrapper that clears filters for columns that are being hidden
  const handleColumnVisibilityChange = useCallback(
    (newVisibility: Record<string, boolean>) => {
      if (gridRef.current?.api) {
        const currentFilterModel = gridRef.current.api.getFilterModel() || {};
        let filtersRemoved = false;
        const newFilterModel: Record<string, unknown> = {};

        for (const [field, filter] of Object.entries(currentFilterModel)) {
          if (newVisibility[field] === false) {
            filtersRemoved = true;
          } else {
            newFilterModel[field] = filter;
          }
        }

        if (filtersRemoved) {
          gridRef.current.api.setFilterModel(newFilterModel);
        }
      }

      setColumnVisibility(newVisibility);
    },
    [setColumnVisibility],
  );

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
    loadLogs(logPath);
  }, [loadLogs, logPath]);

  const handleResetFilters = () => {
    if (gridRef.current?.api) {
      gridRef.current.api.setFilterModel(null);
    }
  };

  const filterModel = gridRef.current?.api?.getFilterModel() || {};
  const filteredFields = Object.keys(filterModel);
  const hasFilter = filteredFields.length > 0;

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

        {hasRetriedLogs && (
          <NavbarButton
            key="show-retried"
            label="Show Retried Logs"
            icon={
              showRetriedLogs
                ? ApplicationIcons.toggle.on
                : ApplicationIcons.toggle.off
            }
            latched={showRetriedLogs}
            onClick={() => setShowRetriedLogs(!showRetriedLogs)}
          />
        )}

        <NavbarButton
          key="choose-columns"
          ref={columnButtonRef}
          label="Choose Columns"
          icon={ApplicationIcons.checkbox.checked}
          onClick={(e) => {
            e.stopPropagation();
            setShowColumnSelector((prev) => !prev);
          }}
        />

        <ViewSegmentedControl selectedSegment="logs" />
        {flowData && <FlowButton />}
      </ApplicationNavbar>

      <ColumnSelectorPopover
        showing={showColumnSelector}
        setShowing={setShowColumnSelector}
        columns={columns}
        onVisibilityChange={handleColumnVisibilityChange}
        positionEl={columnButtonRef.current}
        filteredFields={filteredFields}
      />

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

  collapsedLogItems.push(...pendingTasks);

  return collapsedLogItems;
};
