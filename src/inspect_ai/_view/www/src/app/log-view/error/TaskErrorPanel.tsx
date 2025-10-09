import { FC } from "react";
import { ApplicationIcons } from "../../appearance/icons";

import { EvalError } from "../../../@types/log";
import { ANSIDisplay } from "../../../components/AnsiDisplay";
import { Card, CardBody, CardHeader } from "../../../components/Card";

import clsx from "clsx";
import ExpandablePanel from "../../../components/ExpandablePanel";
import { RenderedContent } from "../../content/RenderedContent";
import styles from "./TaskErrorPanel.module.css";

interface TaskErrorProps {
  error: EvalError;
}

export const TaskErrorCard: FC<TaskErrorProps> = ({ error }) => {
  return (
    <Card>
      <CardHeader
        icon={ApplicationIcons.error}
        label={`Task Failed`}
      ></CardHeader>
      <CardBody>
        <ExpandablePanel
          id="task-error-collapse"
          collapse={true}
          className={clsx("text-size-smaller", styles.message)}
        >
          <RenderedContent
            id="task-error-message"
            entry={{ name: "error", value: error.message }}
          />
        </ExpandablePanel>
        <ANSIDisplay
          output={error.traceback_ansi}
          className={styles["task-error-display"]}
        />
      </CardBody>
    </Card>
  );
};
