import clsx from "clsx";
import { FC } from "react";
import styles from "./WebSearch.module.css";

export const WebSearch: FC<{ query: string }> = ({ query }) => {
  return (
    <div className={clsx(styles.webSearch, "text-size-smaller")}>
      <span className={clsx("text-style-label", "text-style-secondary")}>
        Web Search:
      </span>
      <span className={clsx(styles.query, "text-size-smallest")}>{query}</span>
    </div>
  );
};
