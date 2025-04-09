import clsx from "clsx";
import { FC, Fragment } from "react";
import { formatDateTime, formatTime } from "../../../../utils/format";
import styles from "./EventTimingPanel.module.css";

interface EventTimingPanelProps {
  timestamp: string;
  completed?: string | null;
  working_start?: number | null;
  working_time?: number | null;
}

interface EventTimingPanelRow {
  label: string | "---";
  value?: string;
  secondary?: boolean;
  bordered?: boolean;
  topMargin?: boolean;
}

/**
 * Renders the ModelUsagePanel component.
 */
export const EventTimingPanel: FC<EventTimingPanelProps> = ({
  timestamp,
  completed,
  working_start,
  working_time,
}) => {
  const rows: EventTimingPanelRow[] = [
    {
      label: "Clock Time",
      value: undefined,
      secondary: false,
    },
    {
      label: "---",
      value: undefined,
      secondary: false,
    },
  ];

  if (!completed) {
    rows.push({
      label: "Timestamp",
      value: formatDateTime(new Date(timestamp)),
    });
  } else {
    rows.push({ label: "Start", value: formatDateTime(new Date(timestamp)) });
    rows.push({ label: "End", value: formatDateTime(new Date(completed)) });
  }

  if (working_start || working_time) {
    rows.push({
      label: "Working Time",
      value: undefined,
      secondary: false,
      topMargin: true,
    });
    rows.push({
      label: "---",
      value: undefined,
      secondary: false,
    });
    if (working_start) {
      rows.push({
        label: "Start",
        value: formatTime(working_start),
      });
    }
    if (working_time) {
      rows.push({
        label: "Duration",
        value: formatTime(working_time),
      });
    }
    if (working_start && working_time) {
      rows.push({
        label: "End",
        value: formatTime(
          Math.round(working_start * 10) / 10 +
            Math.round(working_time * 10) / 10,
        ),
      });
    }
  }

  return (
    <div className={clsx("text-size-small", styles.wrapper)}>
      {rows.map((row, idx) => {
        if (row.label === "---") {
          return (
            <div key={`$usage-sep-${idx}`} className={styles.separator}></div>
          );
        } else {
          return (
            <Fragment key={`$usage-row-${idx}`}>
              <div
                className={clsx(
                  "text-style-label",
                  "text-style-secondary",
                  row.secondary ? styles.col2 : styles.col1_3,
                  row.topMargin ? styles.topMargin : undefined,
                )}
              >
                {row.label}
              </div>
              <div className={styles.col3}>{row.value ? row.value : ""}</div>
            </Fragment>
          );
        }
      })}
    </div>
  );
};
