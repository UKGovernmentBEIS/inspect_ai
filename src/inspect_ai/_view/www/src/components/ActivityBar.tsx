import clsx from "clsx";
import { FC } from "react";
import styles from "./ActivityBar.module.css";

interface ActivityBarProps {
  animating: boolean;
}

export const ActivityBar: FC<ActivityBarProps> = ({ animating }) => {
  return (
    <div className={clsx(styles.wrapper)}>
      <div
        className={clsx(styles.container)}
        role="progressbar"
        aria-label="Progress bar"
        aria-valuenow={25}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        {animating && <div className={styles.animate} />}
      </div>
    </div>
  );
};
