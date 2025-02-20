import clsx from "clsx";
import { DisplayMetric } from "../../api/types";
import { ApplicationIcons } from "../../appearance/icons";
import { formatPrettyDecimal } from "../../utils/format";

import { Fragment } from "react/jsx-runtime";
import styles from "./RunningStatusPanel.module.css";

export interface RunningPanelProps {
  sampleCount: number;
  displayMetrics?: DisplayMetric[];
}

export const RunningStatusPanel: React.FC<RunningPanelProps> = ({
  sampleCount,
  displayMetrics,
}) => {
  const displayableMetrics =
    displayMetrics?.filter((displayMetric) => {
      return displayMetric.value !== undefined;
    }) || [];

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
      <div className={clsx(styles.metricsRows)}>
        {displayableMetrics?.map((displayMetric) => {
          return (
            <Fragment>
              <div className={clsx("text-size-smaller")}>
                {displayMetric.reducer
                  ? `${displayMetric.name} (${displayMetric.reducer})`
                  : `${displayMetric.name}`}
              </div>
              <div className={clsx("text-size-smaller", styles.value)}>
                {formatPrettyDecimal(displayMetric.value!)}
              </div>
            </Fragment>
          );
        })}
      </div>
    </div>
  );
};
