import clsx from "clsx";
import { EvalScore } from "../../types/log";
import { formatPrettyDecimal } from "../../utils/format";

import { metricDisplayName } from "../utils";
import styles from "./SidebarScoreView.module.css";
interface SidebarScoreProps {
  scorer: EvalScore;
}

export const SidebarScoreView: React.FC<SidebarScoreProps> = ({ scorer }) => {
  const showReducer = !!scorer.reducer;
  return (
    <div className={styles.container}>
      {Object.keys(scorer.metrics).map((metric) => {
        return (
          <div className={styles.metric} key={metric}>
            <div
              className={clsx(
                "text-style-secondary",
                "text-style-label",
                "text-size-small",
                styles.metricName,
              )}
            >
              {metricDisplayName(scorer.metrics[metric])}
            </div>
            {showReducer ? (
              <div className={clsx("text-size-small", styles.metricReducer)}>
                {scorer.reducer || "default"}
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
