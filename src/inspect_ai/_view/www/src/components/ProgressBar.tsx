import clsx from "clsx";
import { FC } from "react";
import styles from "./ProgressBar.module.css";

interface ProgressBarProps {
  min: number;
  max: number;
  value: number;
  width?: string;
  label?: string;
}

export const ProgressBar: FC<ProgressBarProps> = ({
  min,
  max,
  value,
  label,
  width = "100px",
}) => {
  return (
    <div className={clsx(styles.container)}>
      <div className={clsx(styles.outer)} style={{ width }}>
        <div
          className={clsx(styles.inner)}
          style={{ width: `${((value - min) / (max - min)) * 100}%` }}
        ></div>
      </div>
      <div className={clsx(styles.label, "text-size-smallest")}>
        {value} / {max} {label || ""}
      </div>
    </div>
  );
};
