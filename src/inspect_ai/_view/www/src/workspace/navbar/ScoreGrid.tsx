import clsx from "clsx";
import { FC } from "react";
import { formatPrettyDecimal } from "../../utils/format";
import { ResultsScorer } from "./ResultsPanel";

import styles from "./ScoreGrid.module.css";

interface ScoreGridProps {
  scoreGroups: ResultsScorer[][];
  showReducer?: boolean;
  className?: string | string[];
}

export const ScoreGrid: FC<ScoreGridProps> = ({
  scoreGroups,
  showReducer,
  className,
}) => {
  const columnCount = scoreGroups.reduce((prev, group) => {
    return Math.max(prev, group[0].metrics.length);
  }, 0);

  const groups = scoreGroups.map((group, index) => {
    const metrics = group[0].metrics;
    const cells = [];

    // Column headings
    cells.push(<div></div>);
    for (let i = 0; i < columnCount; i++) {
      if (metrics.length > i) {
        cells.push(
          <div
            className={clsx(
              "text-style-label",
              "text-style-secondary",
              styles.label,
              index > 0 ? styles.padded : undefined,
            )}
          >
            {metrics[i].name}
          </div>,
        );
      } else {
        cells.push(<div></div>);
      }
    }

    // Column values
    group.map((g) => {
      cells.push(
        <div className={clsx(styles.scorer)}>
          {g.scorer} {showReducer && g.reducer ? `(${g.reducer})` : undefined}
        </div>,
      );
      for (let i = 0; i < columnCount; i++) {
        if (metrics.length > i) {
          cells.push(
            <div className={clsx(styles.value)}>
              {formatPrettyDecimal(g.metrics[i].value)}
            </div>,
          );
        } else {
          cells.push(<div></div>);
        }
      }
    });

    return cells;
  });

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${columnCount + 1}, max-content)`,
        columnGap: "1.5em",
      }}
      className={clsx("text-size-small", className)}
    >
      {groups}
    </div>
  );
};
