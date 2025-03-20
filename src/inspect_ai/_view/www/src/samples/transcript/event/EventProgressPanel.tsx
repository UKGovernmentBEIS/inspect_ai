import clsx from "clsx";
import { FC } from "react";

import styles from "./EventProgressPanel.module.css";

interface EventProgressPanelProps {
  text: string;
}

export const EventProgressPanel: FC<EventProgressPanelProps> = ({ text }) => {
  return (
    <div className={clsx(styles.panel)}>
      <div className={clsx(styles.container)}>
        <Spinner />
        <div className={clsx("text-size-smaller", styles.text)}>{text}</div>
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
