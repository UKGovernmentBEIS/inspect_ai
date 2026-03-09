import clsx from "clsx";
import { FC, useMemo } from "react";
import type { EarlyStoppingSummary, EvalStats } from "../../../@types/log";
import type { LogDetails } from "../../../client/api/types";
import { Card, CardBody, CardHeader } from "../../../components/Card";
import { kLogViewTaskTabId } from "../../../constants";
import {
  formatDateTime,
  formatDuration,
  formatNumber,
  toTitleCase,
} from "../../../utils/format";
import { ghCommitUrl } from "../../../utils/git";

import { MetaDataGrid } from "../../content/MetaDataGrid";
import { RecordTree } from "../../content/RecordTree";
import styles from "./TaskTab.module.css";

// Individual hook for Info tab
export const useTaskTabConfig = (
  log: LogDetails | undefined,
  evalStats?: EvalStats,
  earlyStopping?: EarlyStoppingSummary | null,
) => {
  return useMemo(() => {
    return {
      id: kLogViewTaskTabId,
      label: "Task",
      scrollable: true,
      component: TaskTab,
      componentProps: {
        log,
        evalStats,
        earlyStopping,
      },
    };
  }, [log, evalStats, earlyStopping]);
};

interface TaskTabProps {
  log?: LogDetails;
  evalStats?: EvalStats;
  earlyStopping?: EarlyStoppingSummary | null;
}

export const TaskTab: FC<TaskTabProps> = ({
  log,
  evalStats,
  earlyStopping,
}) => {
  const evalSpec = log?.eval;
  const revision = evalSpec?.revision;
  const packages = evalSpec?.packages;
  const tags = log?.tags || [];
  const metadata = (log?.metadata || {}) as Record<string, unknown>;

  const taskInformation: Record<string, unknown> = {
    ["Task ID"]: evalSpec?.task_id,
    ["Run ID"]: evalSpec?.run_id,
  };

  if (revision) {
    taskInformation[
      `${revision.type ? `${toTitleCase(revision.type)} ` : ""}Revision`
    ] = {
      _html: (
        <a href={ghCommitUrl(revision.origin, revision.commit)}>
          {revision.commit}
        </a>
      ),
    };
  }
  if (packages) {
    const names = Object.keys(packages).map((key) => {
      return `${key} ${packages[key]}`;
    });

    if (names.length === 1) {
      taskInformation["Inspect"] = names[0];
    } else {
      taskInformation["Inspect"] = names;
    }
  }
  if (tags.length > 0) {
    taskInformation["tags"] = tags.join(", ");
  }

  if (evalSpec?.sandbox) {
    if (Array.isArray(evalSpec?.sandbox)) {
      taskInformation["sandbox"] = evalSpec.sandbox[0];
      if (evalSpec.sandbox[1]) {
        taskInformation["sandbox_config"] = evalSpec.sandbox[1];
      }
    } else {
      taskInformation["sandbox"] = evalSpec?.sandbox.type;
      taskInformation["sandbox_config"] = evalSpec?.sandbox.config;
    }
  }

  const totalDuration = formatDuration(
    new Date(evalStats?.started_at || 0),
    new Date(evalStats?.completed_at || 0),
  );

  const task_args = evalSpec?.task_args || {};

  return (
    <div style={{ width: "100%" }}>
      <div style={{ padding: "0.5em 1em 0 1em", width: "100%" }}>
        <Card>
          <CardHeader label="Task Info" />
          <CardBody id={"task-card-config"}>
            <div className={clsx(styles.grid)}>
              <MetaDataGrid
                key={`plan-md-task`}
                className={"text-size-small"}
                entries={taskInformation}
              />

              <MetaDataGrid
                entries={{
                  ["Start"]: formatDateTime(
                    new Date(evalStats?.started_at || 0),
                  ),
                  ["End"]: formatDateTime(
                    new Date(evalStats?.completed_at || 0),
                  ),
                  ["Duration"]: totalDuration,
                }}
              />
            </div>
          </CardBody>
        </Card>

        {earlyStopping && (
          <Card>
            <CardHeader
              label={`Early Stopping (${earlyStopping.manager} — ${formatNumber(earlyStopping.early_stops.length)} skipped)`}
            />
            <CardBody>
              <RecordTree
                id={`early-stopping-metadata`}
                record={earlyStopping.metadata}
              />
            </CardBody>
          </Card>
        )}

        {Object.keys(task_args).length > 0 && (
          <Card>
            <CardHeader label="Task Args" />
            <CardBody id={"task-card-config"}>
              <MetaDataGrid
                key={`plan-md-task-args`}
                className={"text-size-small"}
                entries={task_args as Record<string, unknown>}
              />
            </CardBody>
          </Card>
        )}

        {Object.keys(metadata).length > 0 && (
          <Card>
            <CardHeader label="Metadata" />
            <CardBody>
              <RecordTree id={`task-metadata`} record={metadata} />
            </CardBody>
          </Card>
        )}
      </div>
    </div>
  );
};
