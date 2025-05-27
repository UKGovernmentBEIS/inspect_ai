interface LogListFooterProps {
  itemCount: number;
  running: boolean;
}

import clsx from "clsx";
import { FC } from "react";
import styles from "./LogListFooter.module.css";
import { LogPager } from "./LogPager";
import { useStore } from "../../state/store";

export const LogListFooter: FC<LogListFooterProps> = ({
  itemCount,
  running,
}) => {

  const page = useStore((state) => state.logs.page);
  const itemsPerPage = useStore((state) => state.logs.itemsPerPage);
  const pageItemCount = Math.min(
    itemsPerPage,
    itemCount - (page || 0) * itemsPerPage,
  );


  
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
        <div>{`${pageItemCount} / ${itemCount} items`}</div>
      </div>
      <div className={clsx(styles.right)}>
        <LogPager itemCount={itemCount} /></div>
    </div>
  );
};
