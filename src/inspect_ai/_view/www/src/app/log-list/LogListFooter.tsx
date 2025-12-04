import clsx from "clsx";
import { FC, ReactNode } from "react";
import { usePagination } from "../../state/hooks";
import styles from "./LogListFooter.module.css";
import { LogPager } from "./LogPager";

interface LogListFooterProps {
  id: string;
  itemCount: number;
  itemCountLabel?: string;
  paginated: boolean;
  filteredCount?: number;
  pagesize?: number;
  progressText?: string;
  progressBar?: ReactNode;
}

export const LogListFooter: FC<LogListFooterProps> = ({
  id,
  itemCount,
  itemCountLabel,
  paginated,
  pagesize,
  filteredCount,
  progressText,
  progressBar,
}) => {
  // Get pagination info from the store
  const { page, itemsPerPage } = usePagination(id, pagesize || itemCount);

  // Get filtered count from the store
  const effectiveItemCount = filteredCount ?? itemCount;

  // Compute the start and end items
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
        ) : itemCountLabel ? (
          `${itemCount.toLocaleString()} ${itemCountLabel}`
        ) : null}
      </div>
      <div className={clsx(styles.center)}>
        {paginated && <LogPager itemCount={effectiveItemCount} />}
      </div>
      <div className={clsx(styles.right)}>
        {progressBar ? (
          progressBar
        ) : paginated ? (
          <div>
            {effectiveItemCount === 0
              ? ""
              : filteredCount !== undefined && filteredCount !== itemCount
                ? `${startItem} - ${endItem} / ${effectiveItemCount} (${itemCount} total)`
                : `${startItem} - ${endItem} / ${effectiveItemCount}`}
          </div>
        ) : (
          `${effectiveItemCount} items`
        )}
      </div>
    </div>
  );
};
