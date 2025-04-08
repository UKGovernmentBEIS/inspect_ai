import clsx from "clsx";
import { FC } from "react";

import styles from "./RunningNoSamples.module.css";

interface RunningNoSamplesProps {}

export const RunningNoSamples: FC<RunningNoSamplesProps> = () => {
  return (
    <div className={clsx(styles.panel)}>
      <div className={clsx(styles.container, "text-size-smaller")}>
        <div className={clsx(styles.spinner, "spinner-border")} role="status">
          <span className={clsx("visually-hidden")}>starting...</span>
        </div>
        <div className={clsx(styles.text)}>starting....</div>
      </div>
    </div>
  );
};
