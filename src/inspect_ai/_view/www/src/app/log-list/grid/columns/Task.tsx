import { Link } from "react-router-dom";
import { FileLogItem, FolderLogItem, PendingTaskItem } from "../../LogItem";
import { columnHelper } from "./columns";

import { parseLogFileName } from "../../../../utils/evallog";
import styles from "./Task.module.css";

export const taskColumn = () => {
  return columnHelper.accessor((row) => itemName(row), {
    id: "task",
    header: "Task",
    cell: (info) => {
      const item = info.row.original as
        | FileLogItem
        | FolderLogItem
        | PendingTaskItem;
      let value = itemName(item);
      return (
        <div className={styles.nameCell}>
          {item.url ? (
            <Link to={item.url} className={styles.logLink} title={item.name}>
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
    size: 250,
    minSize: 150,
    enableResizing: true,
    sortingFn: (rowA, rowB) => {
      const itemA = rowA.original as
        | FileLogItem
        | FolderLogItem
        | PendingTaskItem;
      const itemB = rowB.original as
        | FileLogItem
        | FolderLogItem
        | PendingTaskItem;

      const valueA = itemName(itemA);
      const valueB = itemName(itemB);

      return valueA.localeCompare(valueB);
    },
  });
};

const itemName = (item: FileLogItem | FolderLogItem | PendingTaskItem) => {
  let value = item.name;
  if (item.type === "file") {
    return item.logPreview?.task || parseLogFileName(item.name).name;
  }
  return value;
};
