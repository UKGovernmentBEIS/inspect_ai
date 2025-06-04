import { Link } from "react-router-dom";
import { FileLogItem, FolderLogItem } from "../../LogItem";
import { columnHelper } from "./columns";

import { EvalLogHeader } from "../../../../client/api/types";
import { parseLogFileName } from "../../../../utils/evallog";
import styles from "./Task.module.css";

export const taskColumn = (logHeaders: Record<string, EvalLogHeader>) => {
  return columnHelper.accessor("name", {
    id: "task",
    header: "Task",
    cell: (info) => {
      const item = info.row.original as FileLogItem | FolderLogItem;
      let value = itemName(item, logHeaders);
      return (
        <div className={styles.nameCell}>
          {item.url ? (
            <Link to={item.url} className={styles.logLink}>
              {value}
            </Link>
          ) : (
            value
          )}
        </div>
      );
    },
    enableSorting: true,
    enableGlobalFilter: true,
    size: 450,
    minSize: 150,
    enableResizing: true,
    sortingFn: (rowA, rowB) => {
      const itemA = rowA.original as FileLogItem | FolderLogItem;
      const itemB = rowB.original as FileLogItem | FolderLogItem;

      const valueA = itemName(itemA, logHeaders);
      const valueB = itemName(itemB, logHeaders);

      return valueA.localeCompare(valueB);
    },
  });
};

const itemName = (
  item: FileLogItem | FolderLogItem,
  logHeaders: Record<string, EvalLogHeader>,
) => {
  let value = item.name;
  if (item.type === "file") {
    if (logHeaders[item.logFile?.name || ""]?.eval.task) {
      value = logHeaders[item.logFile?.name || ""].eval.task;
    } else {
      const parsed = parseLogFileName(item.name);
      value = parsed.name;
    }
  }
  return value;
};
