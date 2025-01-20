import clsx from "clsx";
import { SampleSummary } from "../api/Types";
import { ApplicationIcons } from "../appearance/icons";
import { CopyButton } from "../components/CopyButton";
import { EvalResults, EvalSpec, Status } from "../types/log";
import { filename } from "../utils/path";
import styles from "./PrimaryBar.module.css";
import { ResultsPanel } from "./ResultsPanel";
import { CancelledPanel, ErroredPanel, RunningPanel } from "./StatusPanel";

interface PrimaryBarProps {
  showToggle: boolean;
  offcanvas: boolean;
  status?: Status;
  evalResults?: EvalResults;
  samples?: SampleSummary[];
  file?: string;
  evalSpec?: EvalSpec;
}

export const PrimaryBar: React.FC<PrimaryBarProps> = ({
  showToggle,
  offcanvas,
  status,
  evalResults,
  samples,
  file,
  evalSpec,
}) => {
  let statusPanel;
  if (status === "success") {
    statusPanel = <ResultsPanel results={evalResults} />;
  } else if (status === "cancelled") {
    statusPanel = <CancelledPanel sampleCount={samples?.length || 0} />;
  } else if (status === "started") {
    statusPanel = <RunningPanel sampleCount={samples?.length || 0} />;
  } else if (status === "error") {
    statusPanel = <ErroredPanel sampleCount={samples?.length || 0} />;
  }
  const logFileName = file ? filename(file) : "";

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
            className={clsx(
              "btn",
              offcanvas ? undefined : "d-md-none",
              styles.toggle,
            )}
            type="button"
            data-bs-toggle="offcanvas"
            data-bs-target="#sidebarOffCanvas"
            aria-controls="sidebarOffCanvas"
          >
            <i class={ApplicationIcons.menu}></i>
          </button>
        ) : (
          ""
        )}
        <div className={styles.body}>
          <div className={styles.bodyContainer}>
            <div
              id="task-title"
              className={clsx("task-title", "text-wrap", styles.taskTitle)}
              title={evalSpec?.task}
            >
              {evalSpec?.task}
            </div>
            <div
              id="task-model"
              className={clsx(
                "task-model",
                "text-wrap",
                styles.taskModel,
                "text-size-base",
              )}
              title={evalSpec?.model}
            >
              {evalSpec?.model}
            </div>
          </div>
          <div className={clsx("text-size-small", styles.secondaryContainer)}>
            <div className={clsx("navbar-secondary-text", "text-wrap")}>
              {logFileName}
            </div>
            {file ? <CopyButton value={file} /> : ""}
          </div>
        </div>
      </div>
      <div className={clsx(styles.taskStatus, "navbar-text")}>
        {statusPanel}
      </div>
    </div>
  );
};
