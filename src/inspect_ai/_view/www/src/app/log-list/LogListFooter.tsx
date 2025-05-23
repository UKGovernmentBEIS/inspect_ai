interface LogListFooterProps {
  itemCount: number;
  running: boolean;
}

import clsx from "clsx";
import { FC } from "react";
import styles from "./LogListFooter.module.css";

export const LogListFooter: FC<LogListFooterProps> = ({
  itemCount,
  running,
}) => {
  return (
    <div className={clsx("text-size-smaller", styles.footer)}>
      <div>
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
      </div>
      <div>{`${itemCount} items`}</div>
    </div>
  );
};
