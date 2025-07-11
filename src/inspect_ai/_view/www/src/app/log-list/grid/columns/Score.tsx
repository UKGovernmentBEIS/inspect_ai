import { formatPrettyDecimal } from "../../../../utils/format";
import { FileLogItem, FolderLogItem } from "../../LogItem";
import { columnHelper } from "./columns";
import { EmptyCell } from "./EmptyCell";

import styles from "./Score.module.css";

export const scoreColumn = () => {
  return columnHelper.accessor(
    (row) => {
      const metric = itemMetric(row);
      return metric?.value !== undefined
        ? formatPrettyDecimal(metric.value)
        : "";
    },
    {
      id: "score",
      header: "Score",
      cell: (info) => {
        const metric = itemMetric(info.row.original);
        if (metric === undefined) {
          return <EmptyCell />;
        }
        return (
          <div className={styles.scoreCell}>
            {formatPrettyDecimal(metric.value)}
          </div>
        );
      },
      sortingFn: (rowA, rowB) => {
        const itemA = rowA.original;
        const itemB = rowB.original;

        const metricA = itemMetric(itemA);
        const metricB = itemMetric(itemB);

        if (!metricA && !metricB) return 0;
        if (!metricA) return -1;
        if (!metricB) return 1;

        return (metricA.value || 0) - (metricB.value || 0);
      },
      enableSorting: true,
      enableGlobalFilter: true,
      size: 80,
      minSize: 60,
      maxSize: 120,
      enableResizing: true,
    },
  );
};

const itemMetric = (item: FileLogItem | FolderLogItem) => {
  if (item.type !== "file") {
    return undefined;
  }

  return item.logOverview?.primary_metric;
};
