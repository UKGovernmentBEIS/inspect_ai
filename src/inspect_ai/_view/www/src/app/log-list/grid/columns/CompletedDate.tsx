import { EvalLogHeader } from "../../../../client/api/types";
import { FileLogItem, FolderLogItem } from "../../LogItem";
import { columnHelper } from "./columns";

import styles from "./CompletedDate.module.css";

export const completedDateColumn = (
  logHeaders: Record<string, EvalLogHeader>,
) => {
  return columnHelper.accessor("name", {
    id: "completed",
    header: "Completed",
    cell: (info) => {
      const item = info.row.original;
      const header =
        item.type === "file"
          ? logHeaders[item?.logFile?.name || ""]
          : undefined;

      const completed = header?.stats?.completed_at;
      const time = completed ? new Date(completed) : undefined;
      const timeStr = time
        ? `${time.toDateString()}
        ${time.toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        })}`
        : "";

      return <div className={styles.dateCell}>{timeStr}</div>;
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

      const timeA = new Date(headerA?.stats?.completed_at || 0);
      const timeB = new Date(headerB?.stats?.completed_at || 0);
      return timeA.getTime() - timeB.getTime();
    },

    enableSorting: true,
    enableGlobalFilter: true,
    size: 200,
    minSize: 120,
    maxSize: 300,
    enableResizing: true,
  });
};
