interface LogListFooterProps {
  logDir: string;
  itemCount: number;
  running: boolean;
}

import clsx from "clsx";
import { FC } from "react";
import { usePagination } from "../../state/hooks";
import styles from "./LogListFooter.module.css";
import { LogPager } from "./LogPager";
import { kDefaultPageSize, kLogsPaginationId } from "./LogsPanel";

export const LogListFooter: FC<LogListFooterProps> = ({
  itemCount,
  running,
}) => {
  const { page, itemsPerPage } = usePagination(
    kLogsPaginationId,
    kDefaultPageSize,
  );

  const pageItemCount = Math.min(
    itemsPerPage,
    itemCount - (page || 0) * itemsPerPage,
  );
  const startItem = (page || 0) * itemsPerPage + 1;
  const endItem = startItem + pageItemCount - 1;

  return (
    <div className={clsx("text-size-smaller", styles.footer)}>
      <div className={clsx(styles.left)}>
        {running ? (
          <div className={clsx(styles.spinnerContainer)}>
            <div
              className={clsx("spinner-border", styles.spinner)}
              role="status"
            >
              <span className={clsx("visually-hidden")}>Running...</span>
            </div>
            <div className={clsx("text-style-secondary", styles.label)}>
              running...
            </div>
          </div>
        ) : undefined}
        <div>{`${startItem} - ${endItem} / ${itemCount}`}</div>
      </div>
      <div className={clsx(styles.right)}>
        <LogPager itemCount={itemCount} />
      </div>
    </div>
  );
};
