import clsx from "clsx";
import { FC } from "react";
import { Link } from "react-router-dom";
import { ApplicationIcons } from "../appearance/icons";
import { LogItem } from "./LogItem";

import styles from "./LogRow.module.css";

interface LogRowProps {
  item: LogItem;
}

export const LogRow: FC<LogRowProps> = ({ item }) => {
  return (
    <>
      <div>
        <i
          className={clsx(
            item.type === "file"
              ? ApplicationIcons.file
              : ApplicationIcons.folder,
          )}
        />
      </div>
      <div className={clsx(styles.logLink)}>
        {item.url ? <Link to={item.url}>{item.name}</Link> : item.name}
      </div>
    </>
  );
};
