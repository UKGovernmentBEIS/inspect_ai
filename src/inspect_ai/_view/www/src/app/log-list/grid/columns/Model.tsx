import { EvalLogHeader } from "../../../../client/api/types";
import { FileLogItem, FolderLogItem } from "../../LogItem";
import { columnHelper } from "./columns";
import { EmptyCell } from "./EmptyCell";

import styles from "./Model.module.css";

export const modelColumn = (logHeaders: Record<string, EvalLogHeader>) => {
  return columnHelper.accessor("name", {
    id: "model",
    header: "Model",
    cell: (info) => {
      const item = info.row.original;
      const header =
        item.type === "file"
          ? logHeaders[item?.logFile?.name || ""]
          : undefined;
      if (!header?.eval.model) {
        return <EmptyCell />;
      }
      return <div className={styles.modelCell}>{header?.eval.model || ""}</div>;
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

      const modelA = headerA?.eval.model || "";
      const modelB = headerB?.eval.model || "";

      return modelA.localeCompare(modelB);
    },

    enableSorting: true,
    enableGlobalFilter: true,
    size: 300,
    minSize: 100,
    maxSize: 400,
    enableResizing: true,
  });
};
