import { EvalLogHeader } from "../../../../client/api/types";
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
    enableSorting: true,
    enableGlobalFilter: true,
    size: 200,
    minSize: 120,
    maxSize: 300,
    enableResizing: true,
  });
};
