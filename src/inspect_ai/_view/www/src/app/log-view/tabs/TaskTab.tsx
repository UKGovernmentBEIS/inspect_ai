import clsx from "clsx";
import { FC, useMemo } from "react";
import { EvalSpec, EvalStats } from "../../../@types/log";
import { Card, CardBody, CardHeader } from "../../../components/Card";
import { kLogViewTaskTabId } from "../../../constants";
import { formatDuration, toTitleCase } from "../../../utils/format";
import { ghCommitUrl } from "../../../utils/git";

import { MetaDataGrid } from "../../content/MetaDataGrid";
import styles from "./TaskTab.module.css";

// Individual hook for Info tab
export const useTaskTabConfig = (
  evalSpec: EvalSpec | undefined,
  evalStats?: EvalStats,
) => {
  return useMemo(() => {
    return {
      id: kLogViewTaskTabId,
      label: "Task",
      scrollable: true,
      component: TaskTab,
      componentProps: {
        evalSpec,
        evalStats,
      },
    };
  }, [evalSpec, evalStats]);
};

interface TaskTabProps {
  evalSpec?: EvalSpec;
  evalStats?: EvalStats;
}

export const TaskTab: FC<TaskTabProps> = ({ evalSpec, evalStats }) => {
  const config: Record<string, unknown> = {};
  Object.entries(evalSpec?.config || {}).forEach((entry) => {
    const key = entry[0];
    const value = entry[1];
    config[key] = value;
  });

  const revision = evalSpec?.revision;
  const packages = evalSpec?.packages;

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
  if (evalSpec?.tags) {
    taskInformation["tags"] = evalSpec?.tags.join(", ");
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
                  ["Start"]: new Date(
                    evalStats?.started_at || 0,
                  ).toLocaleString(),
                  ["End"]: new Date(
                    evalStats?.completed_at || 0,
                  ).toLocaleString(),
                  ["Duration"]: totalDuration,
                }}
              />
            </div>
          </CardBody>
        </Card>

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
      </div>
    </div>
  );
};
