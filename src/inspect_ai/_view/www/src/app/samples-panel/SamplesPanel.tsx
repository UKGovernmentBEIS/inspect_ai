import clsx from "clsx";

import { AgGridReact } from "ag-grid-react";
import { FC, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityBar } from "../../components/ActivityBar";
import { ProgressBar } from "../../components/ProgressBar";
import {
  LogHandleWithretried,
  useLogs,
  useLogsWithretried,
} from "../../state/hooks";
import { useStore } from "../../state/store";
import { join } from "../../utils/uri";
import { ApplicationIcons } from "../appearance/icons";
import { FlowButton } from "../flow/FlowButton";
import { useFlowServerData } from "../flow/hooks";
import { LogListFooter } from "../log-list/LogListFooter";
import { ApplicationNavbar } from "../navbar/ApplicationNavbar";
import { NavbarButton } from "../navbar/NavbarButton";
import { ViewSegmentedControl } from "../navbar/ViewSegmentedControl";
import { samplesUrl, useSamplesRouteParams } from "../routing/url";
import { ColumnSelectorPopover } from "../shared/ColumnSelectorPopover";
import { useSampleColumns } from "./samples-grid/hooks";
import { SamplesGrid } from "./samples-grid/SamplesGrid";
import styles from "./SamplesPanel.module.css";
import { SampleRow } from "./samples-grid/types";
import { inputString } from "../../utils/format";

export const SamplesPanel: FC = () => {
  const { samplesPath } = useSamplesRouteParams();
  const { loadLogs } = useLogs();
  const logDir = useStore((state) => state.logs.logDir);

  const loading = useStore((state) => state.app.status.loading);
  const syncing = useStore((state) => state.app.status.syncing);
  const showRetriedLogs = useStore((state) => state.logs.showRetriedLogs);
  const setShowRetriedLogs = useStore(
    (state) => state.logsActions.setShowRetriedLogs,
  );

  const filteredSamplesCount = useStore(
    (state) => state.log.filteredSampleCount,
  );
  const setFilteredSampleCount = useStore(
    (state) => state.logActions.setFilteredSampleCount,
  );

  const gridRef = useRef<AgGridReact>(null);
  const [showColumnSelector, setShowColumnSelector] = useState(false);
  const columnButtonRef = useRef<HTMLButtonElement>(null);

  const logDetails = useStore((state) => state.logs.logDetails);
  const { columns, setColumnVisibility } = useSampleColumns(logDetails);

  // Wrapper that clears filters for columns that are being hidden
  const handleColumnVisibilityChange = useCallback(
    (newVisibility: Record<string, boolean>) => {
      // Clear filters for columns that are being hidden
      if (gridRef.current?.api) {
        const currentFilterModel = gridRef.current.api.getFilterModel() || {};
        let filtersRemoved = false;
        const newFilterModel: Record<string, unknown> = {};

        // Copy filters, skipping those for columns being hidden
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

      // Update column visibility
      setColumnVisibility(newVisibility);
    },
    [setColumnVisibility],
  );

  const handleResetFilters = () => {
    if (gridRef.current?.api) {
      gridRef.current.api.setFilterModel(null);
    }
  };

  useFlowServerData(samplesPath || "");
  const flowData = useStore((state) => state.logs.flow);

  const currentDir = join(samplesPath || "", logDir);

  const evalSet = useStore((state) => state.logs.evalSet);
  const logFiles = useLogsWithretried();
  const logPreviews = useStore((state) => state.logs.logPreviews);

  const currentDirLogFiles = useMemo(() => {
    const files = [];
    for (const logFile of logFiles) {
      const inCurrentDir = logFile.name.startsWith(currentDir);
      const skipped = !showRetriedLogs && logFile.retried;
      if (inCurrentDir && !skipped) {
        files.push(logFile);
      }
    }
    return files;
  }, [currentDir, logFiles, showRetriedLogs]);

  const totalTaskCount = useMemo(() => {
    const currentDirTaskIds = new Set(currentDirLogFiles.map((f) => f.task_id));
    let count = currentDirLogFiles.length;
    for (const task of evalSet?.tasks || []) {
      if (!currentDirTaskIds.has(task.task_id)) {
        count++;
      }
    }
    return count;
  }, [currentDirLogFiles, evalSet]);

  const completedTaskCount = useMemo(() => {
    let count = 0;
    for (const logFile of currentDirLogFiles) {
      const preview = logPreviews[logFile.name];
      if (preview && preview.status !== "started") {
        count++;
      }
    }
    return count;
  }, [logPreviews, currentDirLogFiles]);

  useEffect(() => {
    loadLogs(samplesPath);
  }, [loadLogs, samplesPath]);

  // Filter logDetails based on samplesPath
  const logDetailsInPath = useMemo(() => {
    if (!samplesPath) {
      return logDetails; // Show all samples when no path is specified
    }

    const samplesPathAbs = join(samplesPath, logDir);

    return Object.entries(logDetails).reduce(
      (acc, [logFile, details]) => {
        // Check if the logFile starts with the samplesPath
        if (logFile.startsWith(samplesPathAbs)) {
          acc[logFile] = details;
        }
        return acc;
      },
      {} as typeof logDetails,
    );
  }, [logDetails, logDir, samplesPath]);

  // Transform logDetails into flat rows
  const [sampleRows, hasRetriedLogs] = useMemo(() => {
    const allRows: SampleRow[] = [];
    let displayIndex = 1;

    let anyLogInCurrentDirCouldBeSkipped = false;
    const logInCurrentDirByName = currentDirLogFiles.reduce(
      (acc: Record<string, LogHandleWithretried>, log) => {
        if (log.retried) {
          anyLogInCurrentDirCouldBeSkipped = true;
        }
        acc[log.name] = log;
        return acc;
      },
      {},
    );

    Object.entries(logDetailsInPath).forEach(([logFile, logDetail]) => {
      logDetail.sampleSummaries.forEach((sampleSummary) => {
        const row: SampleRow = {
          logFile,
          created: logDetail.eval.created,
          task: logDetail.eval.task || "",
          model: logDetail.eval.model || "",
          status: logDetail.status,
          sampleId: sampleSummary.id,
          epoch: sampleSummary.epoch,
          input: inputString(sampleSummary.input).join("\n"),
          target: Array.isArray(sampleSummary.target)
            ? sampleSummary.target.join(", ")
            : sampleSummary.target,
          error: sampleSummary.error,
          limit: sampleSummary.limit,
          retries: sampleSummary.retries,
          completed: sampleSummary.completed || false,
          displayIndex: displayIndex++,
        };

        // Add scores as individual fields
        if (sampleSummary.scores) {
          Object.entries(sampleSummary.scores).forEach(([scoreName, score]) => {
            row[`score_${scoreName}`] = score.value;
          });
        }

        allRows.push(row);
      });
    });

    const _sampleRows = allRows.filter(
      (row) => row.logFile in logInCurrentDirByName,
    );
    const _hasRetriedLogs =
      _sampleRows.length < allRows.length || anyLogInCurrentDirCouldBeSkipped;

    return [_sampleRows, _hasRetriedLogs];
  }, [logDetailsInPath, currentDirLogFiles]);

  const filterModel = gridRef.current?.api?.getFilterModel() || {};
  const filteredFields = Object.keys(filterModel);
  const hasFilter = filteredFields.length > 0;

  return (
    <div className={clsx(styles.panel)}>
      <ApplicationNavbar currentPath={samplesPath} fnNavigationUrl={samplesUrl}>
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
            onClick={() => {
              setShowRetriedLogs(!showRetriedLogs);
              // update number of samples displayed in lower right corner when toggling
              setTimeout(() => {
                if (gridRef.current) {
                  setFilteredSampleCount(
                    gridRef.current.api.getDisplayedRowCount(),
                  );
                }
              }, 10);
            }}
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

        <ViewSegmentedControl selectedSegment="samples" />
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

      <ActivityBar animating={!!loading} />
      <div className={clsx(styles.list, "text-size-smaller")}>
        <SamplesGrid
          items={sampleRows}
          samplesPath={samplesPath}
          gridRef={gridRef}
          columns={columns}
        />
      </div>

      <LogListFooter
        itemCount={filteredSamplesCount ?? 0}
        itemCountLabel={filteredSamplesCount === 1 ? "sample" : "samples"}
        progressText={
          syncing
            ? `Syncing${filteredSamplesCount ? ` (${filteredSamplesCount.toLocaleString()} samples)` : ""}`
            : undefined
        }
        progressBar={
          totalTaskCount !== completedTaskCount ? (
            <ProgressBar
              min={0}
              max={totalTaskCount}
              value={completedTaskCount}
              width="100px"
              label={"tasks"}
            />
          ) : undefined
        }
      />
    </div>
  );
};
