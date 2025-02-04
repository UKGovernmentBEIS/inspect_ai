import clsx from "clsx";
import styles from "./SampleSeparator.module.css";

interface SampleSeparatorProps {
  id: string;
  title: string;
  height: number;
}

export const SampleSeparator: React.FC<SampleSeparatorProps> = ({
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
