import { forwardRef, useCallback } from "react";

import clsx from "clsx";
import { TextInput } from "../../components/TextInput";
import { useLogsListing } from "../../state/hooks";
import { ApplicationIcons } from "../appearance/icons";
import styles from "./LogsFilterInput.module.css";

export interface LogsToolbarProps {}

export const LogsFilterInput = forwardRef<HTMLInputElement, LogsToolbarProps>(
  (_props, ref) => {
    const { globalFilter, setGlobalFilter } = useLogsListing();
    const handleChange = useCallback(
      async (value: string) => {
        setGlobalFilter(value);
      },
      [setGlobalFilter],
    );

    return (
      <TextInput
        ref={ref}
        icon={ApplicationIcons.filter}
        value={globalFilter || ""}
        onChange={(e) => {
          handleChange(e.target.value);
        }}
        onFocus={(e) => {
          e.target.select();
        }}
        placeholder="Filter..."
        className={clsx(styles.filterInput)}
      />
    );
  },
);
