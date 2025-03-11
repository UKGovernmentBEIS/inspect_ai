import clsx from "clsx";
import { FC } from "react";

import styles from "./TranscriptLoadingPanel.module.css";

interface TranscriptLoadingPanelProps {}

export const TranscriptLoadingPanel: FC<TranscriptLoadingPanelProps> = () => {
  return (
    <div className={clsx(styles.panel)}>
      <div className={clsx(styles.container)}>
        <Spinner />
        <div className={clsx("text-size-smaller", styles.text)}>
          generating...
        </div>
      </div>
    </div>
  );
};

const Spinner: FC = () => {
  return (
    <div className={clsx(styles.spinner, "spinner-border")} role="status">
      <span className={clsx("visually-hidden")}>generating...</span>
    </div>
  );
};
