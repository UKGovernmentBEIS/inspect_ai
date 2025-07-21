import { Link } from "react-router-dom";
import { FileLogItem, FolderLogItem } from "../../LogItem";
import { columnHelper } from "./columns";

import { parseLogFileName } from "../../../../utils/evallog";
import styles from "./Task.module.css";

export const taskColumn = () => {
  return columnHelper.accessor((row) => itemName(row), {
    id: "task",
    header: "Task",
    cell: (info) => {
      const item = info.row.original as FileLogItem | FolderLogItem;
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
      const itemA = rowA.original as FileLogItem | FolderLogItem;
      const itemB = rowB.original as FileLogItem | FolderLogItem;

      const valueA = itemName(itemA);
      const valueB = itemName(itemB);

      return valueA.localeCompare(valueB);
    },
  });
};

const itemName = (item: FileLogItem | FolderLogItem) => {
  let value = item.name;
  if (item.type === "file") {
    return item.logOverview?.task || parseLogFileName(item.name).name;
  }
  return value;
};
