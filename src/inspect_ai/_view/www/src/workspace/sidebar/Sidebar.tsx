import clsx from "clsx";
import { FC, useCallback } from "react";
import { Fragment } from "react/jsx-runtime";
import { EvalLogHeader, LogFiles } from "../../api/types";
import { ApplicationIcons } from "../../appearance/icons";
import { ProgressBar } from "../../components/ProgressBar";
import { useStore } from "../../state/store";
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

        <ul className={clsx("list-group", styles.list)}>
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
                onClick={() => onSelectedIndexChanged(index)}
              >
                <SidebarLogEntry
                  logHeader={logHeader}
                  task={file.task || "unknown task"}
                />
              </li>
            );
          })}
        </ul>
      </div>
    </Fragment>
  );
};
