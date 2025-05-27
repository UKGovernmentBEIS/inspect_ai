import clsx from "clsx";
import { FC, useCallback } from "react";
import { EvalResults, EvalSpec, Status } from "../../../@types/log";
import { RunningMetric } from "../../../client/api/types";
import { CopyButton } from "../../../components/CopyButton";
import { kModelNone } from "../../../constants";
import { useStore } from "../../../state/store";
import { filename } from "../../../utils/path";
import { ApplicationIcons } from "../../appearance/icons";
import { ModelRolesView } from "./ModelRolesView";
import styles from "./PrimaryBar.module.css";
import {
  displayScorersFromRunningMetrics,
  ResultsPanel,
  toDisplayScorers,
} from "./ResultsPanel";
import { RunningStatusPanel } from "./RunningStatusPanel";
import { CancelledPanel, ErroredPanel } from "./StatusPanel";

interface PrimaryBarProps {
  showToggle: boolean;
  status?: Status;
  evalResults?: EvalResults | null;
  runningMetrics?: RunningMetric[];
  evalSpec?: EvalSpec;
  sampleCount?: number;
}

export const PrimaryBar: FC<PrimaryBarProps> = ({
  showToggle,
  status,
  evalResults,
  runningMetrics,
  evalSpec,
  sampleCount,
}) => {
  const offCanvas = useStore((state) => state.app.offcanvas);
  const setOffCanvas = useStore((state) => state.appActions.setOffcanvas);
  const streamSamples = useStore((state) => state.capabilities.streamSamples);
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);

  const logFileName = selectedLogFile ? filename(selectedLogFile) : "";

  const handleToggle = useCallback(() => {
    setOffCanvas(!offCanvas);
  }, [offCanvas, setOffCanvas]);

  const hasRunningMetrics = runningMetrics && runningMetrics.length > 0;

  return (
    <div className={clsx(styles.wrapper)}>
      <div
        className={clsx(
          "navbar-brand",
          "navbar-text",
          "mb-0",
          styles.container,
        )}
      >
        {showToggle ? (
          <button
            id="sidebarToggle"
            onClick={handleToggle}
            className={clsx(
              "btn",
              offCanvas ? "d-md-none" : undefined,
              styles.toggle,
            )}
            type="button"
          >
            <i className={ApplicationIcons.menu}></i>
          </button>
        ) : (
          ""
        )}
        <div className={styles.body}>
          <div className={styles.bodyContainer}>
            <div
              id="task-title"
              className={clsx("task-title", "text-truncate", styles.taskTitle)}
              title={evalSpec?.task}
            >
              {evalSpec?.task}
            </div>
            {evalSpec?.model && evalSpec.model !== kModelNone ? (
              <div
                id="task-model"
                className={clsx(
                  "task-model",
                  "text-truncate",
                  styles.taskModel,
                  "text-size-base",
                )}
                title={evalSpec?.model}
              >
                {evalSpec?.model}
              </div>
            ) : (
              ""
            )}
          </div>
          {evalSpec?.model_roles ? (
            <ModelRolesView roles={evalSpec.model_roles} />
          ) : undefined}

          <div className={clsx("text-size-small", styles.secondaryContainer)}>
            <div className={clsx("navbar-secondary-text", "text-truncate")}>
              {logFileName}
            </div>
            {selectedLogFile ? <CopyButton value={selectedLogFile} /> : ""}
          </div>
        </div>
      </div>
      <div className={clsx(styles.taskStatus, "navbar-text")}>
        {status === "success" ||
        (status === "started" && streamSamples && hasRunningMetrics) ? (
          <ResultsPanel
            scorers={
              runningMetrics
                ? displayScorersFromRunningMetrics(runningMetrics)
                : toDisplayScorers(evalResults?.scores)
            }
          />
        ) : undefined}
        {status === "cancelled" ? (
          <CancelledPanel sampleCount={sampleCount || 0} />
        ) : undefined}
        {status === "started" && (!streamSamples || !hasRunningMetrics) ? (
          <RunningStatusPanel sampleCount={sampleCount || 0} />
        ) : undefined}
        {status === "error" ? (
          <ErroredPanel sampleCount={sampleCount || 0} />
        ) : undefined}
      </div>
      <div id="task-created" style={{ display: "none" }}>
        {evalSpec?.created}
      </div>
    </div>
  );
};
