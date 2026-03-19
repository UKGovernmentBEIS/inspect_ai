import clsx from "clsx";
import { FC } from "react";
import styles from "./ActivityBar.module.css";

interface ActivityBarProps {
  animating: boolean;
  progress?: number;
}

export const ActivityBar: FC<ActivityBarProps> = ({ animating, progress }) => {
  return (
    <div className={clsx(styles.wrapper)}>
      <div
        className={clsx(styles.container)}
        role="progressbar"
        aria-label="Progress bar"
        aria-valuenow={
          progress !== undefined ? Math.round(progress * 100) : undefined
        }
        aria-valuemin={0}
        aria-valuemax={100}
      >
        {animating &&
          (progress !== undefined ? (
            <div
              className={styles.determinate}
              style={{ width: `${progress * 100}%` }}
            />
          ) : (
            <div className={styles.animate} />
          ))}
      </div>
    </div>
  );
};
