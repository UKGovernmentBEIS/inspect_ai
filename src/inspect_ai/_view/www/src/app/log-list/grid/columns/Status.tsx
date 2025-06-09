import clsx from "clsx";
import { FileLogItem, FolderLogItem } from "../../LogItem";
import { columnHelper } from "./columns";
import { EmptyCell } from "./EmptyCell";

import { ApplicationIcons } from "../../../appearance/icons";
import styles from "./Status.module.css";

export const statusColumn = () => {
  return columnHelper.accessor((row) => itemStatus(row), {
    id: "status",
    header: "Status",
    cell: (info) => {
      const item = info.row.original;
      const status = itemStatus(item);

      if (!status) {
        return <EmptyCell />;
      }

      const icon =
        status === "error"
          ? ApplicationIcons.error
          : status === "started"
            ? ApplicationIcons.running
            : status === "cancelled"
              ? ApplicationIcons.cancelled
              : ApplicationIcons.success;

      const clz =
        status === "error"
          ? styles.error
          : status === "started"
            ? styles.started
            : status === "cancelled"
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

      const statusA = itemStatus(itemA) || "";
      const statusB = itemStatus(itemB) || "";

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

const itemStatus = (item: FileLogItem | FolderLogItem) => {
  if (item.type !== "file") {
    return undefined;
  }
  const header = item.header;
  return header?.status;
};
