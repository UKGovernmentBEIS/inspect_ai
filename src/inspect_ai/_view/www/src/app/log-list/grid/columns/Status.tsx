import clsx from "clsx";
import { EvalLogHeader } from "../../../../client/api/types";
import { FileLogItem, FolderLogItem } from "../../LogItem";
import { columnHelper } from "./columns";
import { EmptyCell } from "./EmptyCell";

import { ApplicationIcons } from "../../../appearance/icons";
import styles from "./Status.module.css";

export const statusColumn = (logHeaders: Record<string, EvalLogHeader>) => {
  return columnHelper.accessor("name", {
    id: "status",
    header: "Status",
    cell: (info) => {
      const item = info.row.original;
      const header =
        item.type === "file"
          ? logHeaders[item?.logFile?.name || ""]
          : undefined;

      if (!header) {
        return <EmptyCell />;
      }

      const icon =
        header.status === "error"
          ? ApplicationIcons.error
          : header.status === "started"
            ? ApplicationIcons.running
            : header.status === "cancelled"
              ? ApplicationIcons.cancelled
              : ApplicationIcons.success;

      const clz =
        header.status === "error"
          ? styles.error
          : header.status === "started"
            ? styles.started
            : header.status === "cancelled"
              ? styles.cancelled
              : styles.success;

      return (
        <div className={styles.statusCell}>
          <i className={clsx(icon, clz)} />
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

      const statusA = headerA && headerA.status ? headerA.status : "";
      const statusB = headerB && headerB.status ? headerB.status : "";

      // If A is empty, goes to bottom
      if (!statusA && statusB) {
        return 1;
      }
      // If B is empty, goes to bottom
      if (statusA && !statusB) {
        return -1;
      }

      return statusA.localeCompare(statusB);
    },
    enableSorting: true,
    enableGlobalFilter: true,
    size: 80,
    minSize: 60,
    maxSize: 120,
    enableResizing: true,
  });
};
