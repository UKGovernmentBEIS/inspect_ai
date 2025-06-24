interface LogListFooterProps {
  logDir: string;
  itemCount: number;
  progressText?: string;
}

import clsx from "clsx";
import { FC } from "react";
import { useLogsListing, usePagination } from "../../state/hooks";
import styles from "./LogListFooter.module.css";
import { LogPager } from "./LogPager";
import { kDefaultPageSize, kLogsPaginationId } from "./LogsPanel";

export const LogListFooter: FC<LogListFooterProps> = ({
  itemCount,
  progressText,
}) => {
  // Get pagination info from the store
  const { page, itemsPerPage } = usePagination(
    kLogsPaginationId,
    kDefaultPageSize,
  );

  // Get filtered count from the store
  const { filteredCount } = useLogsListing();
  const effectiveItemCount = filteredCount ?? itemCount;

  const currentPage = page || 0;
  const pageItemCount = Math.min(
    itemsPerPage,
    effectiveItemCount - currentPage * itemsPerPage,
  );
  const startItem = effectiveItemCount > 0 ? currentPage * itemsPerPage + 1 : 0;
  const endItem = startItem + pageItemCount - 1;

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
        ) : undefined}
      </div>
      <div className={clsx(styles.center)}>
        <LogPager itemCount={effectiveItemCount} />
      </div>
      <div className={clsx(styles.right)}>
        <div>
          {effectiveItemCount === 0
            ? ""
            : filteredCount !== undefined && filteredCount !== itemCount
              ? `${startItem} - ${endItem} / ${effectiveItemCount} (${itemCount} total)`
              : `${startItem} - ${endItem} / ${effectiveItemCount}`}
        </div>
      </div>
    </div>
  );
};
