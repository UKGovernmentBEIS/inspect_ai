import clsx from "clsx";
import { FC } from "react";
import styles from "./SampleSeparator.module.css";

interface SampleSeparatorProps {
  id: string;
  title: string;
  height: number;
}

export const SampleSeparator: FC<SampleSeparatorProps> = ({
  id,
  title,
  height,
}) => {
  return (
    <div
      id={id}
      className={clsx("text-style-secondary", "text-size-smaller", styles.row)}
      style={{ height: `${height}px` }}
    >
      <div>{title}</div>
    </div>
  );
};
