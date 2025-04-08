import clsx from "clsx";
import { FC, Fragment } from "react";
import { Scores } from "../../@types/log";
import { formatPrettyDecimal } from "../../utils/format";
import { metricDisplayName } from "../log-view/utils";
import styles from "./SidebarScoresView.module.css";

interface SidebarScoresProps {
  scores: Scores;
}

export const SidebarScoresView: FC<SidebarScoresProps> = ({ scores }) => {
  const showReducer = scores.findIndex((score) => !!score.reducer) !== -1;
  return (
    <div className={styles.container}>
      {scores.map((score, idx) => {
        const name = score.name;
        const reducer = score.reducer;
        return (
          <div className={styles.scoreWrapper} key={`scorer-${name}-${idx}`}>
            <div
              className={clsx(
                "text-style-secondary",
                "text-style-label",
                "text-size-small",
                styles.metricName,
              )}
            >
              {name}
            </div>
            {showReducer ? (
              <div
                className={clsx(
                  "text-size-small",
                  "text-style-label",
                  "text-style-secondary",
                  styles.metricReducer,
                )}
              >
                {reducer || "default"}
              </div>
            ) : (
              ""
            )}
            <div className={clsx("text-size-small", styles.metricValues)}>
              {Object.keys(score.metrics).map((key) => {
                const metric = score.metrics[key];
                return (
                  <Fragment key={key}>
                    <div className={clsx()}>{metricDisplayName(metric)}</div>
                    <div className={styles.metricValue}>
                      {formatPrettyDecimal(metric.value)}
                    </div>
                  </Fragment>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
};
