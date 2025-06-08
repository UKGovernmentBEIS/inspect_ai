import clsx from "clsx";
import { ApplicationIcons } from "../../../appearance/icons";
import { columnHelper } from "./columns";

import styles from "./Icon.module.css";

export const iconColumn = () => {
  return columnHelper.accessor("type", {
    id: "icon",
    header: "",
    cell: (info) => (
      <div className={styles.iconCell}>
        <i
          className={clsx(
            info.getValue() === "file"
              ? ApplicationIcons.inspectFile
              : ApplicationIcons.folder,
          )}
        />
      </div>
    ),
    enableSorting: true,
    enableGlobalFilter: false,
    size: 30,
    minSize: 30,
    maxSize: 60,
    enableResizing: false,
    sortingFn: (rowA, rowB) => {
      const typeA = rowA.original.type;
      const typeB = rowB.original.type;

      return typeA.localeCompare(typeB);
    },
  });
};
