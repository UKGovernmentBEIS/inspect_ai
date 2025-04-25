import clsx from "clsx";
import { FC, Fragment } from "react";
import { ModelUsage1 } from "../../@types/log";
import { formatNumber } from "../../utils/format";
import styles from "./ModelUsagePanel.module.css";

interface ModelUsageProps {
  usage: ModelUsage1;
  className?: string | string[];
}

interface ModelUsageRow {
  label: string | "---";
  value?: number;
  secondary?: boolean;
  bordered?: boolean;
  padded?: boolean;
}

/**
 * Renders the ModelUsagePanel component.
 */
export const ModelUsagePanel: FC<ModelUsageProps> = ({ usage, className }) => {
  if (!usage) {
    return null;
  }

  const rows: ModelUsageRow[] = [];

  if (usage.reasoning_tokens) {
    rows.push({
      label: "Reasoning",
      value: usage.reasoning_tokens,
      secondary: false,
      bordered: true,
    });

    rows.push({
      label: "---",
      value: undefined,
      secondary: false,
      padded: true,
    });
  }

  rows.push({
    label: "input",
    value: usage.input_tokens,
    secondary: false,
  });

  if (usage.input_tokens_cache_read) {
    rows.push({
      label: "cache_read",
      value: usage.input_tokens_cache_read,
      secondary: true,
    });
  }

  if (usage.input_tokens_cache_write) {
    rows.push({
      label: "cache_write",
      value: usage.input_tokens_cache_write,
      secondary: true,
    });
  }

  rows.push({
    label: "Output",
    value: usage.output_tokens,
    secondary: false,
    bordered: true,
  });

  rows.push({
    label: "---",
    value: undefined,
    secondary: false,
  });

  rows.push({
    label: "Total",
    value: usage.total_tokens,
    secondary: false,
  });

  return (
    <div className={clsx("text-size-small", styles.wrapper, className)}>
      {rows.map((row, idx) => {
        if (row.label === "---") {
          return (
            <div
              key={`$usage-sep-${idx}`}
              className={clsx(
                styles.separator,
                row.padded ? styles.padded : undefined,
              )}
            ></div>
          );
        } else {
          return (
            <Fragment key={`$usage-row-${idx}`}>
              <div
                className={clsx(
                  "text-style-label",
                  "text-style-secondary",
                  row.secondary ? styles.col2 : styles.col1_3,
                )}
              >
                {row.label}
              </div>
              <div className={styles.col3}>
                {row.value ? formatNumber(row.value) : ""}
              </div>
            </Fragment>
          );
        }
      })}
    </div>
  );
};
