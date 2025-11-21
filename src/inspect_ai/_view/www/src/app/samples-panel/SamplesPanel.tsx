import clsx from "clsx";

import { AgGridReact } from "ag-grid-react";
import { FC, useEffect, useMemo, useRef } from "react";
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
import { SamplesGrid } from "./samples-grid/SamplesGrid";
import styles from "./SamplesPanel.module.css";

export const SamplesPanel: FC = () => {
  const { samplesPath } = useSamplesRouteParams();
  const { loadLogs } = useLogs();
  const logDir = useStore((state) => state.logs.logDir);

  const loading = useStore((state) => state.app.status.loading);
  const syncing = useStore((state) => state.app.status.syncing);

  const filteredSamplesCount = useStore(
    (state) => state.log.filteredSampleCount,
  );

  const gridRef = useRef<AgGridReact>(null);

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
  }, [logDir, logFiles]);

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

  const filterModel = gridRef.current?.api?.getFilterModel();
  const hasFilter = filterModel && Object.keys(filterModel).length > 0;

  console.log({
    totalTaskCount,
    completedTaskCount,
    showBar: totalTaskCount !== completedTaskCount,
  });

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

        <ViewSegmentedControl selectedSegment="samples" />
        {flowData && <FlowButton />}
      </ApplicationNavbar>

      <ActivityBar animating={!!loading} />
      <div className={clsx(styles.list, "text-size-smaller")}>
        <SamplesGrid samplesPath={samplesPath} gridRef={gridRef} />
      </div>

      <LogListFooter
        id={"samples-list-footer"}
        itemCount={filteredSamplesCount ?? 0}
        paginated={false}
        progressText={syncing ? "Syncing..." : undefined}
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
