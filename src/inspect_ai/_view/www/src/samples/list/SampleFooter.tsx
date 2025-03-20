interface SampleFooterProps {
  sampleCount: number;
  running: boolean;
}

import clsx from "clsx";
import { FC } from "react";
import styles from "./SampleFooter.module.css";

export const SampleFooter: FC<SampleFooterProps> = ({
  sampleCount,
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
      <div>{sampleCount} Samples</div>
    </div>
  );
};
