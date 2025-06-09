import { FC, useCallback } from "react";

import clsx from "clsx";
import { TextInput } from "../../components/TextInput";
import { useLogsListing } from "../../state/hooks";
import { ApplicationIcons } from "../appearance/icons";
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
        <TextInput
          icon={ApplicationIcons.filter}
          value={globalFilter || ""}
          onChange={(e) => {
            debouncedUpdate(e.target.value);
          }}
          placeholder="Filter..."
          className={clsx(styles.filterInput)}
        />
      </div>
      <div className={styles.right}></div>
    </div>
  );
};
