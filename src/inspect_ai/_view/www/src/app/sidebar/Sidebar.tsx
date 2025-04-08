import clsx from "clsx";
import { FC, useCallback, useRef } from "react";
import { Fragment } from "react/jsx-runtime";
import { Link } from "react-router-dom";
import { EvalLogHeader, LogFiles } from "../../client/api/types";
import { ProgressBar } from "../../components/ProgressBar";
import { useStatefulScrollPosition } from "../../state/scrolling";
import { useStore } from "../../state/store";
import { ApplicationIcons } from "../appearance/icons";
import { LogDirectoryTitleView } from "./LogDirectoryTitleView";
import styles from "./Sidebar.module.css";
import { SidebarLogEntry } from "./SidebarLogEntry";

interface SidebarProps {
  logs: LogFiles;
  logHeaders: Record<string, EvalLogHeader>;
  loading: boolean;
  selectedIndex: number;
  onSelectedIndexChanged: (index: number) => void;
}

export const Sidebar: FC<SidebarProps> = ({
  logs,
  logHeaders,
  loading,
  selectedIndex,
  onSelectedIndexChanged,
}) => {
  const setOffCanvas = useStore((state) => state.appActions.setOffcanvas);
  const offCanvas = useStore((state) => state.app.offcanvas);
  const handleToggle = useCallback(() => {
    setOffCanvas(!offCanvas);
  }, [offCanvas, setOffCanvas]);

  const sidebarContentsRef = useRef(null);
  useStatefulScrollPosition(sidebarContentsRef, "sidebar-contents", 1000);

  // No longer need the click handler as we're using Links now

  return (
    <Fragment>
      {/* Optional backdrop for small screens, appears only when offcanvas is open */}
      {offCanvas && <div className={styles.backdrop} onClick={handleToggle} />}

      <div
        className={clsx(
          styles.sidebar,
          offCanvas ? styles.sidebarOpen : styles.sidebarClosed,
        )}
      >
        <div className={styles.header}>
          <LogDirectoryTitleView log_dir={logs.log_dir} />
          <button
            onClick={handleToggle}
            className={clsx("btn", styles.toggle)}
            type="button"
            aria-label="Close sidebar"
          >
            <i className={ApplicationIcons.close}></i>
          </button>
        </div>

        <div className={styles.progress}>
          <ProgressBar animating={loading} />
        </div>

        <ul
          ref={sidebarContentsRef}
          className={clsx("list-group", styles.list)}
        >
          {logs.files.map((file, index) => {
            const logHeader = logHeaders[file.name];
            return (
              <li
                key={file.name}
                className={clsx(
                  "list-group-item",
                  "list-group-item-action",
                  styles.item,
                  selectedIndex === index ? styles.active : undefined,
                )}
                data-index={index}
              >
                <Link
                  to={`/logs/${encodeURIComponent(file.name)}`}
                  className={styles.logLink}
                  onClick={() => {
                    // Also update the current index in state
                    onSelectedIndexChanged(index);
                  }}
                >
                  <SidebarLogEntry
                    logHeader={logHeader}
                    task={file.task || "unknown task"}
                  />
                </Link>
              </li>
            );
          })}
        </ul>
      </div>
    </Fragment>
  );
};
