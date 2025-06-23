import { columnHelper } from "./columns";
import { EmptyCell } from "./EmptyCell";

import styles from "./Model.module.css";

export const modelColumn = () => {
  return columnHelper.accessor("header.eval.model", {
    id: "model",
    header: "Model",
    cell: (info) => {
      const item = info.row.original;
      if (item.type !== "file" || item.header?.eval.model === undefined) {
        return <EmptyCell />;
      }
      return (
        <div className={styles.modelCell}>{item.header?.eval.model || ""}</div>
      );
    },
    enableSorting: true,
    enableGlobalFilter: true,
    size: 300,
    minSize: 100,
    maxSize: 400,
    enableResizing: true,
  });
};
