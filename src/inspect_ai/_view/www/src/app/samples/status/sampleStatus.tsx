import clsx from "clsx";
import { PulsingDots } from "../../../components/PulsingDots";
import { ApplicationIcons } from "../../appearance/icons";
import { errorType } from "../error/error";
import styles from "./sampleStatus.module.css";

type SampleStatus = "running" | "ok" | "error" | "cancelled";
export const sampleStatus = (
  completed?: boolean,
  error?: string,
): SampleStatus => {
  if (error) {
    return errorType(error) === "CancelledError" ? "cancelled" : "error";
  }
  return completed ? "ok" : "running";
};

/** Sortable string value for use as ag-grid valueGetter.
 *  Prefix gives desired sort order (started → error → cancelled → success);
 *  error rows additionally include the error type for sub-sorting. */
export const kDefaultSampleSortValue = "3:ok";
export const sampleStatusSortValue = (
  status: SampleStatus,
  error?: string,
): string => {
  switch (status) {
    case "running":
      return "0:running";
    case "error":
      return `1:error:${errorType(error)}`;
    case "cancelled":
      return "2:cancelled";
    default:
      return kDefaultSampleSortValue;
  }
};

interface SampleStatusIconProps {
  status: SampleStatus;
}

export const SampleStatusIcon = ({ status }: SampleStatusIconProps) => {
  if (status === "running") {
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
