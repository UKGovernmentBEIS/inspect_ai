//@ts-check

import { ApplicationIcons } from "../appearance/icons";
import { ApplicationStyles } from "../appearance/styles";

import clsx from "clsx";
import styles from "./SampleErrorView.module.css";

interface SampleErrorViewProps {
  message?: string;
  align?: string;
  style?: React.CSSProperties;
}

/**
 * Component to display a styled error message.
 */
export const SampleError: React.FC<SampleErrorViewProps> = ({
  message,
  align,
}) => {
  align = align || "center";

  return (
    <div className={styles.body}>
      <i className={clsx(ApplicationIcons.error, styles.iconSmall)} />
      <div className={styles.message} style={ApplicationStyles.lineClamp(2)}>
        {errorType(message)}
      </div>
    </div>
  );
};

interface FlatSampleErrorViewProps {
  message?: string;
}
/**
 * Component to display a styled error message.
 */
export const FlatSampleError: React.FC<FlatSampleErrorViewProps> = ({
  message,
}) => {
  return (
    <div className={clsx(styles.flatBody)}>
      <i className={clsx(ApplicationIcons.error, styles.iconSmall)} />
      <div className={clsx(styles.lineBase)}>{errorType(message)}</div>
    </div>
  );
};

/**
 * Extracts the error type from a given message.
 * If the message contains parentheses, it returns the substring before the first parenthesis.
 * Otherwise, it returns "Error".
 */
const errorType = (message?: string): string => {
  if (!message) {
    return "Error";
  }

  if (message.includes("(")) {
    return message.split("(")[0];
  }
  return "Error";
};
