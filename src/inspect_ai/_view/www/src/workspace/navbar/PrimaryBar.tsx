import clsx from "clsx";
import { FC, useCallback } from "react";
import { RunningMetric, SampleSummary } from "../../api/types";
import { ApplicationIcons } from "../../appearance/icons";
import { CopyButton } from "../../components/CopyButton";
import { kModelNone } from "../../constants";
import { Capabilities } from "../../types";
import { EvalResults, EvalSpec, Status } from "../../types/log";
import { filename } from "../../utils/path";
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
  offcanvas: boolean;
  setOffcanvas: (offcanvas: boolean) => void;
  status?: Status;
  evalResults?: EvalResults;
  runningMetrics?: RunningMetric[];
  samples?: SampleSummary[];
  file?: string;
  evalSpec?: EvalSpec;
  capabilities: Capabilities;
}

export const PrimaryBar: FC<PrimaryBarProps> = ({
  showToggle,
  offcanvas,
  status,
  evalResults,
  runningMetrics,
  samples,
  file,
  evalSpec,
  setOffcanvas,
  capabilities,
}) => {
  const logFileName = file ? filename(file) : "";
  console.log({ runningMetrics });

  const handleToggle = useCallback(() => {
    setOffcanvas(!offcanvas);
  }, [setOffcanvas, offcanvas]);

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
              offcanvas ? "d-md-none" : undefined,
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
          <div className={clsx("text-size-small", styles.secondaryContainer)}>
            <div className={clsx("navbar-secondary-text", "text-truncate")}>
              {logFileName}
            </div>
            {file ? <CopyButton value={file} /> : ""}
          </div>
        </div>
      </div>
      <div className={clsx(styles.taskStatus, "navbar-text")}>
        {status === "success" ||
        (status === "started" && capabilities.streamSamples) ? (
          <ResultsPanel
            scorers={
              runningMetrics
                ? displayScorersFromRunningMetrics(runningMetrics)
                : toDisplayScorers(evalResults?.scores)
            }
          />
        ) : undefined}
        {status === "cancelled" ? (
          <CancelledPanel sampleCount={samples?.length || 0} />
        ) : undefined}
        {status === "started" && !capabilities.streamSamples ? (
          <RunningStatusPanel sampleCount={samples?.length || 0} />
        ) : undefined}
        {status === "error" ? (
          <ErroredPanel sampleCount={samples?.length || 0} />
        ) : undefined}
      </div>
      <div id="task-created" style={{ display: "none" }}>
        {evalSpec?.created}
      </div>
    </div>
  );
};
