import { Link } from "react-router-dom";
import { FileLogItem, FolderLogItem, PendingTaskItem } from "../../LogItem";
import { columnHelper } from "./columns";

import { basename } from "../../../../utils/path";
import { EmptyCell } from "./EmptyCell";
import styles from "./FileName.module.css";

export const fileNameColumn = () => {
  return columnHelper.accessor("name", {
    id: "file_name",
    header: "File Name",
    cell: (info) => {
      const item = info.row.original as
        | FileLogItem
        | FolderLogItem
        | PendingTaskItem;
      if (item.type === "folder" || item.type === "pending-task") {
        return <EmptyCell />;
      }
      let value = basename(item.name);
      return (
        <div className={styles.nameCell}>
          {item.url ? (
            <Link to={item.url} className={styles.fileLink}>
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
    size: 600,
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

      // Sort folders first, then files
      if (itemA.type !== itemB.type) {
        return itemA.type === "folder" ? -1 : 1;
      }

      // Within same type, sort by basename
      const valueA = basename(itemA.name);
      const valueB = basename(itemB.name);

      return valueA.localeCompare(valueB);
    },
  });
};
