import { ApplicationIcons } from "../../appearance/icons";

import clsx from "clsx";
import styles from "./SampleErrorView.module.css";
import { errorType } from "./error";

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
