import clsx from "clsx";
import { FC } from "react";
import { ApplicationIcons } from "../../appearance/icons";

import styles from "./NoSamples.module.css";

interface NoSamplesPanelProps {}

export const NoSamplesPanel: FC<NoSamplesPanelProps> = () => {
  return (
    <div className={clsx(styles.panel)}>
      <div className={clsx(styles.container, "text-size-smaller")}>
        <i className={ApplicationIcons.noSamples} />
        <div>No samples</div>
      </div>
    </div>
  );
};
