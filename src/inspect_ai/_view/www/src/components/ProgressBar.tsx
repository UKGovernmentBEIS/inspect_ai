import clsx from "clsx";
import { FC } from "react";
import styles from "./ProgressBar.module.css";

interface ProgressBarProps {
  animating: boolean;
  fixed?: boolean;
}

export const ProgressBar: FC<ProgressBarProps> = ({
  animating,
  fixed = true,
}) => {
  return (
    <div className={clsx(styles.wrapper)}>
      <div
        className={clsx(styles.container, fixed ? styles.fixed : undefined)}
        role="progressbar"
        aria-label="Basic example"
        aria-valuenow={25}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        {animating && <div className={styles.animate} />}
      </div>
    </div>
  );
};
