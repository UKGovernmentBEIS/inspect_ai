import clsx from "clsx";
import { FC } from "react";
import { useAppContext } from "../../AppContext";
import styles from "./LogDirectoryTitleView.module.css";

interface LogDirectoryTitleViewProps {
  log_dir?: string;
}

export const LogDirectoryTitleView: FC<LogDirectoryTitleViewProps> = ({
  log_dir,
}) => {
  const appContext = useAppContext();
  if (log_dir) {
    const displayDir = prettyDir(log_dir);
    return (
      <div style={{ display: "flex", flexDirection: "column" }}>
        <span
          className={clsx(
            "text-style-secondary",
            "text-style-label",
            "text-size-small",
          )}
        >
          Log Directory
        </span>
        <span
          title={displayDir}
          className={clsx("text-size-base", styles.dirname)}
        >
          {appContext.state.offcanvas ? displayDir : ""}
        </span>
      </div>
    );
  } else {
    return (
      <span className={clsx("text-size-title")}>
        {appContext.state.offcanvas ? "Log History" : ""}
      </span>
    );
  }
};

const prettyDir = (path: string): string => {
  try {
    // Try to create a new URL object
    let url = new URL(path);

    if (url.protocol === "file:") {
      return url.pathname;
    } else {
      return path;
    }
  } catch {
    return path;
  }
};
