import { FC, useCallback } from "react";

import clsx from "clsx";
import { TextInput } from "../../components/TextInput";
import { useLogsListing } from "../../state/hooks";
import { ApplicationIcons } from "../appearance/icons";
import styles from "./LogsFilterInput.module.css";

export interface LogsToolbarProps {}

export const LogsFilterInput: FC<LogsToolbarProps> = () => {
  const { globalFilter, setGlobalFilter } = useLogsListing();
  const debouncedUpdate = useCallback(
    async (value: string) => {
      setGlobalFilter(value);
    },
    [setGlobalFilter],
  );

  return (
    <TextInput
      icon={ApplicationIcons.filter}
      value={globalFilter || ""}
      onChange={(e) => {
        debouncedUpdate(e.target.value);
      }}
      placeholder="Filter..."
      className={clsx(styles.filterInput)}
    />
  );
};
