import { ApplicationIcons } from "../../appearance/icons";
import { ApplicationStyles } from "../../appearance/styles";

import clsx from "clsx";
import { CSSProperties, FC } from "react";
import styles from "./SampleErrorView.module.css";
import { errorType } from "./error";

interface SampleErrorViewProps {
  message?: string;
  align?: string;
  style?: CSSProperties;
}

/**
 * Component to display a styled error message.
 */
export const SampleErrorView: FC<SampleErrorViewProps> = ({
  message,
  align,
}) => {
  align = align || "center";

  const type = errorType(message);

  return (
    <div
      className={clsx(
        styles.body,
        isCanceledError(type) ? styles.safe : undefined,
      )}
    >
      <i className={clsx(ApplicationIcons.error, styles.iconSmall)} />
      <div className={styles.message} style={ApplicationStyles.lineClamp(2)}>
        {type}
      </div>
    </div>
  );
};

const isCanceledError = (type?: string) => {
  return type === "CancelledError";
};
