import clsx from "clsx";
import { FC, ReactNode } from "react";
import { formatPrettyDecimal } from "../../utils/format";
import { ResultsScorer } from "./ResultsPanel";

import styles from "./ScoreGrid.module.css";

interface ScoreGridProps {
  scoreGroups: ResultsScorer[][];
  showReducer?: boolean;
  className?: string | string[];
  striped?: boolean;
}

export const ScoreGrid: FC<ScoreGridProps> = ({
  scoreGroups,
  showReducer,
  className,
  striped,
}) => {
  const columnCount = scoreGroups.reduce((prev, group) => {
    return Math.max(prev, group[0].metrics.length);
  }, 0);

  const subTables: ReactNode[] = [];

  let index = 0;
  for (const scoreGroup of scoreGroups) {
    const metrics = scoreGroup[0].metrics;

    // Add header row

    const cells: ReactNode[] = [];
    for (let i = 0; i < columnCount; i++) {
      if (metrics.length > i) {
        cells.push(
          <th
            className={clsx(
              "text-style-label",
              "text-style-secondary",
              "text-size-small",
              styles.label,
            )}
          >
            {metrics[i].name}
          </th>,
        );
      } else {
        cells.push(<td></td>);
      }
    }

    const headerRow = (
      <tr className={clsx(styles.headerRow)}>
        <td></td>
        {cells}
      </tr>
    );
    const rows: ReactNode[] = [];
    scoreGroup.forEach((g) => {
      const cells: ReactNode[] = [];
      for (let i = 0; i < columnCount; i++) {
        if (metrics.length > i) {
          cells.push(
            <td className={clsx(styles.value, "text-size-small")}>
              {formatPrettyDecimal(g.metrics[i].value)}
            </td>,
          );
        } else {
          cells.push(<td className={clsx(styles.value)}></td>);
        }
      }

      rows.push(
        <tr>
          <th className={clsx(styles.scorer, "text-size-small")}>
            {g.scorer} {showReducer && g.reducer ? `(${g.reducer})` : undefined}
          </th>
          {cells}
        </tr>,
      );
    });

    subTables.push(
      <>
        {index > 0 ? (
          <tr>
            <td
              colSpan={columnCount + 1}
              className={clsx(styles.groupSeparator)}
            ></td>
          </tr>
        ) : undefined}
        {headerRow}
        <tbody className={clsx("table-group-divider", styles.tableBody)}>
          {rows}
        </tbody>
      </>,
    );

    index++;
  }

  return (
    <table
      className={clsx(
        className,
        "table",
        striped ? "table-striped" : undefined,
        styles.table,
        "table-bordered",
      )}
    >
      {subTables}
    </table>
  );
};
