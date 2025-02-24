import clsx from "clsx";
import { FC, useCallback } from "react";
import { Fragment } from "react/jsx-runtime";
import { EvalLogHeader, LogFiles } from "../../api/types";
import { useAppContext } from "../../AppContext";
import { ApplicationIcons } from "../../appearance/icons";
import { ProgressBar } from "../../components/ProgressBar";
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
  const appContext = useAppContext();
  const handleToggle = useCallback(() => {
    appContext.dispatch({
      type: "SET_OFFCANVAS",
      payload: !appContext.state.offcanvas,
    });
  }, [appContext.state.offcanvas, appContext.dispatch]);

  return (
    <Fragment>
      {/* Optional backdrop for small screens, appears only when offcanvas is open */}
      {appContext.state.offcanvas && (
        <div className={styles.backdrop} onClick={handleToggle} />
      )}

      <div
        className={clsx(
          styles.sidebar,
          appContext.state.offcanvas
            ? styles.sidebarOpen
            : styles.sidebarClosed,
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
