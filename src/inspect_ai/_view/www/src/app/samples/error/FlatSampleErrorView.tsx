import { ApplicationIcons } from "../../appearance/icons";

import clsx from "clsx";
import { FC } from "react";
import styles from "./FlatSampleErrorView.module.css";
import { errorType } from "./error";

interface FlatSampleErrorViewProps {
  message?: string;
}
/**
 * Component to display a styled error message.
 */
export const FlatSampleError: FC<FlatSampleErrorViewProps> = ({ message }) => {
  return (
    <div className={clsx(styles.flatBody)}>
      <i className={clsx(ApplicationIcons.error, styles.iconSmall)} />
      <div className={clsx(styles.lineBase, "text-truncate")}>
        {errorType(message)}
      </div>
    </div>
  );
};
