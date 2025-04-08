import { FC } from "react";
import { ApplicationIcons } from "../../appearance/icons";

import { EvalError } from "../../../@types/log";
import { ANSIDisplay } from "../../../components/AnsiDisplay";
import { Card, CardBody, CardHeader } from "../../../components/Card";

import styles from "./TaskErrorPanel.module.css";

interface TaskErrorProps {
  error: EvalError;
}

export const TaskErrorCard: FC<TaskErrorProps> = ({ error }) => {
  return (
    <Card>
      <CardHeader
        icon={ApplicationIcons.error}
        label="Task Failed: ${error.message}"
      ></CardHeader>
      <CardBody>
        <ANSIDisplay
          output={error.traceback_ansi}
          className={styles["task-error-display"]}
        />
      </CardBody>
    </Card>
  );
};
