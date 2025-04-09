import clsx from "clsx";
import { FC } from "react";

import { ApplicationIcons } from "../app/appearance/icons";
import styles from "./NoContentsPanel.module.css";

interface NoContentsPanelProps {
  text: string;
}

export const NoContentsPanel: FC<NoContentsPanelProps> = ({ text }) => {
  return (
    <div className={clsx(styles.panel)}>
      <div className={clsx(styles.container, "text-size-smaller")}>
        <i className={ApplicationIcons.noSamples} />
        <div>{text}</div>
      </div>
    </div>
  );
};
