import clsx from "clsx";
import { FC } from "react";
import { Status } from "../../../@types/log";
import { PulsingDots } from "../../../components/PulsingDots";
import { ApplicationIcons } from "../../appearance/icons";
import { errorType } from "../error/error";
import styles from "./sampleStatus.module.css";

/** Derive a `Status` from completed flag + error string. */
export const sampleStatus = (completed: boolean, error?: string): Status => {
  if (error) {
    return errorType(error) === "CancelledError" ? "cancelled" : "error";
  }
  return completed ? "success" : "started";
};

/** Sortable string value for use as ag-grid valueGetter.
 *  Prefix gives desired sort order (started → error → cancelled → success);
 *  error rows additionally include the error type for sub-sorting. */
export const sampleStatusValue = (status: Status, error?: string): string => {
  switch (status) {
    case "started":
      return "0:started";
    case "error":
      return `1:error:${errorType(error)}`;
    case "cancelled":
      return "2:cancelled";
    case "success":
      return "3:success";
  }
};

interface SampleStatusIconProps {
  status: Status;
}

export const SampleStatusIcon: FC<SampleStatusIconProps> = ({ status }) => {
  if (status === "started") {
    return (
      <div className={styles.statusCell}>
        <PulsingDots subtle={false} />
      </div>
    );
  }

  const icon =
    status === "error"
      ? ApplicationIcons.error
      : status === "cancelled"
        ? ApplicationIcons.cancelled
        : ApplicationIcons.success;

  const colorClass =
    status === "error"
      ? styles.error
      : status === "cancelled"
        ? styles.cancelled
        : styles.success;

  return (
    <div className={styles.statusCell}>
      <i className={clsx(icon, colorClass)} />
    </div>
  );
};
