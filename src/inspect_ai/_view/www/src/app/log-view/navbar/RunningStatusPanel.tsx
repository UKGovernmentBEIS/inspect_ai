import clsx from "clsx";
import { RunningMetric } from "../../../client/api/types";
import { ApplicationIcons } from "../../appearance/icons";

import { FC } from "react";
import styles from "./RunningStatusPanel.module.css";

export interface RunningPanelProps {
  sampleCount: number;
  displayMetrics?: RunningMetric[];
}

export const RunningStatusPanel: FC<RunningPanelProps> = ({ sampleCount }) => {
  return (
    <div>
      <div className={clsx(styles.statusContainer)}>
        <div className={clsx(styles.status)}>
          <i className={clsx(ApplicationIcons.running, styles.icon)} />
          <div
            className={clsx(
              styles.statusText,
              "text-style-label",
              "text-size-smaller",
            )}
          >
            Running ({sampleCount} samples)
          </div>
        </div>
      </div>
    </div>
  );
};
