import clsx from "clsx";
import React from "preact/compat";
import { Scores } from "../../types/log";
import { formatPrettyDecimal } from "../../utils/format";
import styles from "./SidebarScoresView.module.css";

interface SidebarScoresProps {
  scores: Scores;
}

export const SidebarScoresView: React.FC<SidebarScoresProps> = ({ scores }) => {
  return (
    <div className={styles.container}>
      {scores.map((score) => {
        const name = score.name;
        const reducer = score.reducer;
        return (
          <div className={styles.scoreWrapper}>
            <div
              className={clsx(
                "text-style-secondary",
                "text-label",
                "text-size-small",
                styles.metricName,
              )}
            >
              {name}
            </div>
            {reducer ? (
              <div className={clsx("text-size-small", styles.metricReducer)}>
                {reducer}
              </div>
            ) : (
              ""
            )}
            <div className={clsx("text-size-small", styles.metricValues)}>
              {Object.keys(score.metrics).map((key) => {
                const metric = score.metrics[key];
                return (
                  <React.Fragment key={key}>
                    <div
                      className={clsx(
                        "text-style-secondary",
                        "text-style-label",
                      )}
                    >
                      {metric.name}
                    </div>
                    <div className={styles.metricValue}>
                      {formatPrettyDecimal(metric.value)}
                    </div>
                  </React.Fragment>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
};
