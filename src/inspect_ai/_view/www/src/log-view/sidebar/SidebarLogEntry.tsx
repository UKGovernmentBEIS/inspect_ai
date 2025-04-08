import clsx from "clsx";
import { FC, Fragment } from "react";
import { EvalLogHeader } from "../../client/api/types";
import { kModelNone } from "../../constants";
import { EvalStatus } from "./EvalStatus";
import styles from "./SidebarLogEntry.module.css";

interface SidebarLogEntryProps {
  logHeader?: EvalLogHeader;
  task: string;
}

export const SidebarLogEntry: FC<SidebarLogEntryProps> = ({
  logHeader,
  task,
}) => {
  const hyperparameters: Record<string, unknown> = {
    ...(logHeader?.plan?.config || {}),
    ...(logHeader?.eval?.task_args || {}),
  };

  const model = logHeader?.eval?.model;
  const datasetName = logHeader?.eval?.dataset.name;

  const uniqScorers = new Set();
  logHeader?.results?.scores?.forEach((scorer) => {
    uniqScorers.add(scorer.name);
  });
  const scorerNames = Array.from(uniqScorers).join(",");

  const scorerLabel =
    Object.keys(logHeader?.results?.scores || {}).length === 1
      ? "scorer"
      : "scorers";

  const completed = logHeader?.stats?.completed_at;
  const time = completed ? new Date(completed) : undefined;
  const timeStr = time
    ? `${time.toDateString()}
    ${time.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    })}`
    : "";

  return (
    <Fragment>
      <div className={styles.entry}>
        <div className={styles.title}>
          <div className={clsx(styles.task, "text-size-title-secondary")}>
            {logHeader?.eval?.task || task}
          </div>
          <small className={clsx("mb-1", "text-size-small")}>{timeStr}</small>

          {model && model !== kModelNone ? (
            <div>
              <small className={clsx("mb-1", "text-size-small")}>{model}</small>
            </div>
          ) : (
            ""
          )}
        </div>
        <EvalStatus logHeader={logHeader} />
      </div>
      <div className={clsx(styles.params, "three-line-clamp")}>
        <small className={"mb-1"}>
          {hyperparameters
            ? Object.keys(hyperparameters)
                .map((key) => {
                  const val = hyperparameters[key];
                  if (Array.isArray(val) || typeof val === "object") {
                    return `${key}: ${JSON.stringify(val)}`;
                  } else {
                    return `${key}: ${val}`;
                  }
                })
                .join(", ")
            : ""}
        </small>
      </div>
      {(logHeader?.eval?.dataset || logHeader?.results?.scores) &&
      logHeader?.status === "success" ? (
        <div
          className={clsx("text-truncate", "text-size-small", styles.scores)}
        >
          <div>dataset: {datasetName || "(samples)"}</div>
          <div className={clsx("text-truncate", styles.scoreInfo)}>
            {scorerLabel}: {scorerNames || "(none)"}
          </div>
        </div>
      ) : (
        ""
      )}
    </Fragment>
  );
};
