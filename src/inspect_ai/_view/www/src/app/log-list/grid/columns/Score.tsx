import { EvalLogHeader } from "../../../../client/api/types";
import { firstMetric } from "../../../../scoring/metrics";
import { formatPrettyDecimal } from "../../../../utils/format";
import { FileLogItem, FolderLogItem } from "../../LogItem";
import { columnHelper } from "./columns";
import { EmptyCell } from "./EmptyCell";

import styles from "./Score.module.css";

export const scoreColumn = (logHeaders: Record<string, EvalLogHeader>) => {
  return columnHelper.accessor("name", {
    id: "score",
    header: "Score",
    cell: (info) => {
      const item = info.row.original;
      const header =
        item.type === "file"
          ? logHeaders[item?.logFile?.name || ""]
          : undefined;

      const metric =
        header && header.results ? firstMetric(header.results) : undefined;
      if (!metric) {
        return <EmptyCell />;
      }
      return (
        <div className={styles.scoreCell}>
          {metric ? formatPrettyDecimal(metric.value) : ""}
        </div>
      );
    },
    sortingFn: (rowA, rowB) => {
      const itemA = rowA.original as FileLogItem | FolderLogItem;
      const itemB = rowB.original as FileLogItem | FolderLogItem;

      const headerA =
        itemA.type === "file"
          ? logHeaders[itemA.logFile?.name || ""]
          : undefined;
      const headerB =
        itemB.type === "file"
          ? logHeaders[itemB.logFile?.name || ""]
          : undefined;

      const metricA =
        headerA && headerA.results ? firstMetric(headerA.results) : undefined;
      const metricB =
        headerB && headerB.results ? firstMetric(headerB.results) : undefined;

      // Sort files without scores before files with scores (empty values at top when ascending)
      if (!metricA && metricB) return -1;
      if (metricA && !metricB) return 1;
      if (!metricA && !metricB) return 0;

      return (metricA?.value || 0) - (metricB?.value || 0);
    },
    enableSorting: true,
    enableGlobalFilter: true,
    size: 80,
    minSize: 60,
    maxSize: 120,
    enableResizing: true,
  });
};
