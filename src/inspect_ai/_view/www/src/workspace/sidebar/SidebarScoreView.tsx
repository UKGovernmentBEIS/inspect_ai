import clsx from "clsx";
import { EvalScore } from "../../types/log";
import { formatPrettyDecimal } from "../../utils/format";

import styles from "./SidebarScoreView.module.css";
interface SidebarScoreProps {
  scorer: EvalScore;
}

export const SidebarScoreView: React.FC<SidebarScoreProps> = ({ scorer }) => {
  return (
    <div className={styles.container}>
      {Object.keys(scorer.metrics).map((metric) => {
        return (
          <div className={styles.metric}>
            <div
              className={clsx(
                "text-style-secondary",
                "text-style-label",
                "text-size-small",
                styles.metricName,
              )}
            >
              {scorer.metrics[metric].name}
            </div>
            {scorer.reducer ? (
              <div className={clsx("text-size-small", styles.metricReducer)}>
                ${scorer.reducer}
              </div>
            ) : (
              ""
            )}
            <div className={"text-size-title-secondary"}>
              {formatPrettyDecimal(scorer.metrics[metric].value)}
            </div>
          </div>
        );
      })}
    </div>
  );
};
