interface SampleHeaderProps {
  input?: boolean;
  target?: boolean;
  answer?: boolean;
  limit?: boolean;
  score?: boolean;
  gridColumnsTemplate: string;
}
import clsx from "clsx";
import styles from "./SampleHeader.module.css";

export const SampleHeader: React.FC<SampleHeaderProps> = ({
  input = true,
  target = true,
  answer = true,
  limit = true,
  score = true,
  gridColumnsTemplate,
}) => (
  <div
    className={clsx(
      styles.header,
      "text-size-smaller",
      "text-style-label",
      "text-style-secondary",
    )}
    style={{ gridTemplateColumns: gridColumnsTemplate }}
  >
    <div>Id</div>
    <div>{input ? "Input" : ""}</div>
    <div>{target ? "Target" : ""}</div>
    <div>{answer ? "Answer" : ""}</div>
    <div>{limit ? "Limit" : ""}</div>
    <div className={styles.center}>{score ? "Score" : ""}</div>
  </div>
);
