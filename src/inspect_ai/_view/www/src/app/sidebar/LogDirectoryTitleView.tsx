import clsx from "clsx";
import { FC, useCallback } from "react";
import { Link } from "react-router-dom";
import { useStore } from "../../state/store";
import styles from "./LogDirectoryTitleView.module.css";

interface LogDirectoryTitleViewProps {
  log_dir?: string;
}

export const LogDirectoryTitleView: FC<LogDirectoryTitleViewProps> = ({
  log_dir,
}) => {
  const offCanvas = useStore((state) => state.app.offcanvas);
  const setOffCanvas = useStore((state) => state.appActions.setOffcanvas);

  const handleClick = useCallback(() => {
    // Close the sidebar when clicking the directory link on mobile
    if (offCanvas) {
      setOffCanvas(false);
    }
  }, [offCanvas, setOffCanvas]);
  if (log_dir) {
    const displayDir = prettyDir(log_dir);
    return (
      <Link to="/logs" className={styles.directoryLink} onClick={handleClick}>
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
            {offCanvas ? displayDir : ""}
          </span>
        </div>
      </Link>
    );
  } else {
    return (
      <Link to="/logs" className={styles.directoryLink} onClick={handleClick}>
        <span className={clsx("text-size-title")}>
          {offCanvas ? "Log History" : ""}
        </span>
      </Link>
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
