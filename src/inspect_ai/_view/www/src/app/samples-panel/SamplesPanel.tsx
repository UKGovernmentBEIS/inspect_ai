import clsx from "clsx";

import { AgGridReact } from "ag-grid-react";
import { FC, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityBar } from "../../components/ActivityBar";
import { ProgressBar } from "../../components/ProgressBar";
import { useLogs } from "../../state/hooks";
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
import { simplifiedStatusForDeduplication } from "../../state/utils";

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
  const logFiles = useStore((state) => state.logs.logs);
  const logPreviews = useStore((state) => state.logs.logPreviews);

  const currentDirLogFiles = useMemo(() => {
    const files = [];
    for (const logFile of logFiles) {
      if (logFile.name.startsWith(currentDir)) {
        files.push(logFile);
      }
    }
    return files;
  }, [currentDir, logFiles]);

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
    const exec = async () => {
      await loadLogs(samplesPath);
    };
    exec();
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
  const [sampleRows, isAnyLogItemHidden] = useMemo(() => {
    const allRows: SampleRow[] = [];
    let displayIndex = 1;

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
          // note: sampleSummary.uuid is different between errored out samples => not useful for de-duplication
          sampleDeDuplicationId: `${logDetail.eval.task_id}-${sampleSummary.id}-${sampleSummary.epoch}`,
          _debug: {
            duplicatesFromPreviousLogs: null,
            logDetail,
            sampleSummary,
          },
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

    if (!evalSet || showRetriedLogs) {
      return [allRows, false];
    }

    const sampleRowsByUuid = allRows.reduce(
      (acc: Record<string, SampleRow[]>, row) => {
        if (!(row.sampleDeDuplicationId in acc))
          acc[row.sampleDeDuplicationId] = [];
        acc[row.sampleDeDuplicationId].push(row);
        return acc;
      },
      {},
    );
    const _sampleRows = Object.values(sampleRowsByUuid).map((rows) => {
      rows.sort((a, b) => {
        const as = simplifiedStatusForDeduplication(a.status);
        const bs = simplifiedStatusForDeduplication(b.status);
        const ac = a.created;
        const bc = b.created;

        if (as === bs) return -ac.localeCompare(bc); // sort by datetime-string, newest on top
        if (as === "started") return -1;
        if (bs === "started") return 1;
        if (as === "success") return -1;
        if (bs === "success") return 1;

        console.warn(`Unexpected status combination: ${as}, ${bs}`, a, b);
        return 0;
      });
      rows[0]._debug.duplicatesFromPreviousLogs = rows.slice(1);
      return rows[0];
    });
    const _isAnyLogItemHidden = _sampleRows.length < allRows.length;

    return [_sampleRows, _isAnyLogItemHidden];
  }, [logDetailsInPath, evalSet, showRetriedLogs]);

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

        {evalSet && (isAnyLogItemHidden || showRetriedLogs) && (
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
