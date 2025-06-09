import { FC, useCallback } from "react";

import { useLogsListing } from "../../state/hooks";
import styles from "./LogsToolbar.module.css";

export interface LogsToolbarProps {}

export const LogsToolbar: FC<LogsToolbarProps> = () => {
  const { globalFilter, setGlobalFilter } = useLogsListing();

  const debouncedUpdate = useCallback(
    async (value: string) => {
      setGlobalFilter(value);
    },
    [setGlobalFilter],
  );

  return (
    <div className={styles.toolbar}>
      <div className={styles.left}>
        <input
          value={globalFilter || ""}
          onChange={(e) => {
            debouncedUpdate(e.target.value);
          }}
          placeholder="Filter..."
          className={styles.searchInput}
        />
      </div>
      <div className={styles.right}></div>
    </div>
  );
};
