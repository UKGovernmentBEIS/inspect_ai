import { columnHelper } from "./columns";
import { EmptyCell } from "./EmptyCell";

import styles from "./Model.module.css";

export const modelColumn = () => {
  return columnHelper.accessor(
    (row) => {
      if (row.type !== "file") return "";
      return row.logOverview?.model || "";
    },
    {
      id: "model",
      header: "Model",
      cell: (info) => {
        const item = info.row.original;
        if (item.type !== "file" || item.logOverview?.model === undefined) {
          return <EmptyCell />;
        }
        return (
          <div className={styles.modelCell}>{item.logOverview.model || ""}</div>
        );
      },
      enableSorting: true,
      enableGlobalFilter: true,
      size: 300,
      minSize: 100,
      maxSize: 400,
      enableResizing: true,
    },
  );
};
