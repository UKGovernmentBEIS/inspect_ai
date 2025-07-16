import { FileLogItem, FolderLogItem } from "../../LogItem";
import { columnHelper } from "./columns";

import styles from "./CompletedDate.module.css";
import { EmptyCell } from "./EmptyCell";

export const completedDateColumn = () => {
  return columnHelper.accessor(
    (row) => {
      const completed = itemCompletedAt(row);
      if (!completed) return "";
      const time = new Date(completed);
      return `${time.toDateString()} ${time.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      })}`;
    },
    {
      id: "completed",
      header: "Completed",
      cell: (info) => {
        const item = info.row.original;
        const completed = itemCompletedAt(item);
        const time = completed ? new Date(completed) : undefined;
        const timeStr = time
          ? `${time.toDateString()}
        ${time.toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        })}`
          : "";

        if (!timeStr) {
          return <EmptyCell />;
        }

        return <div className={styles.dateCell}>{timeStr}</div>;
      },
      sortingFn: (rowA, rowB) => {
        const itemA = rowA.original as FileLogItem | FolderLogItem;
        const itemB = rowB.original as FileLogItem | FolderLogItem;

        const completedA = itemCompletedAt(itemA);
        const completedB = itemCompletedAt(itemB);

        const timeA = new Date(completedA || 0);
        const timeB = new Date(completedB || 0);
        return timeA.getTime() - timeB.getTime();
      },

      enableSorting: true,
      enableGlobalFilter: true,
      size: 200,
      minSize: 120,
      maxSize: 300,
      enableResizing: true,
    },
  );
};

const itemCompletedAt = (item: FileLogItem | FolderLogItem) => {
  if (item.type !== "file") return undefined;
  return item.logOverview?.completed_at;
};
