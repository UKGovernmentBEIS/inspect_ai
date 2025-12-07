import clsx from "clsx";
import { FC, ReactNode } from "react";
import styles from "./LogListFooter.module.css";

interface LogListFooterProps {
  itemCount: number;
  itemCountLabel?: string;
  filteredCount?: number;
  progressText?: string;
  progressBar?: ReactNode;
}

export const LogListFooter: FC<LogListFooterProps> = ({
  itemCount,
  itemCountLabel,
  filteredCount,
  progressText,
  progressBar,
}) => {
  const effectiveItemCount = filteredCount ?? itemCount;

  return (
    <div className={clsx("text-size-smaller", styles.footer)}>
      <div className={clsx(styles.left)}>
        {progressText ? (
          <div className={clsx(styles.spinnerContainer)}>
            <div
              className={clsx("spinner-border", styles.spinner)}
              role="status"
            >
              <span className={clsx("visually-hidden")}>{progressText}...</span>
            </div>
            <div className={clsx("text-style-secondary", styles.label)}>
              {progressText}...
            </div>
          </div>
        ) : null}
      </div>
      <div className={clsx(styles.center)} />
      <div className={clsx(styles.right)}>
        {progressBar ? (
          progressBar
        ) : (
          <div>
            {effectiveItemCount === 0
              ? ""
              : filteredCount !== undefined && filteredCount !== itemCount
                ? `${effectiveItemCount} / ${itemCount} ${itemCountLabel || "items"}`
                : `${effectiveItemCount} ${itemCountLabel || "items"}`}
          </div>
        )}
      </div>
    </div>
  );
};
