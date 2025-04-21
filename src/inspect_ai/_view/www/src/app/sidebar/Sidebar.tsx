import clsx from "clsx";
import { FC, useCallback, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { Fragment } from "react/jsx-runtime";
import { EvalLogHeader } from "../../client/api/types";
import { ProgressBar } from "../../components/ProgressBar";
import { useStatefulScrollPosition } from "../../state/scrolling";
import { useStore } from "../../state/store";
import { ApplicationIcons } from "../appearance/icons";
import { logUrl } from "../routing/url";
import { LogDirectoryTitleView } from "./LogDirectoryTitleView";
import styles from "./Sidebar.module.css";
import { SidebarLogEntry } from "./SidebarLogEntry";

interface SidebarProps {
  logHeaders: Record<string, EvalLogHeader>;
  loading: boolean;
  selectedIndex: number;
  onSelectedIndexChanged: (index: number) => void;
}

export const Sidebar: FC<SidebarProps> = ({
  logHeaders,
  loading,
  selectedIndex,
  onSelectedIndexChanged,
}) => {
  const logs = useStore((state) => state.logs.logs);
  const setOffCanvas = useStore((state) => state.appActions.setOffcanvas);
  const offCanvas = useStore((state) => state.app.offcanvas);
  const handleToggle = useCallback(() => {
    setOffCanvas(!offCanvas);
  }, [offCanvas, setOffCanvas]);

  const sidebarContentsRef = useRef(null);
  useStatefulScrollPosition(sidebarContentsRef, "sidebar-contents", 1000);

  // Scroll the selected log into view when it changes
  const itemRefs = useRef<{ [index: number]: HTMLLIElement | null }>({});

  useEffect(() => {
    if (itemRefs.current[selectedIndex]) {
      itemRefs.current[selectedIndex]?.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      });
    }
  }, [selectedIndex]);

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
                ref={(el) => {
                  itemRefs.current[index] = el;
                }}
                className={clsx(
                  "list-group-item",
                  "list-group-item-action",
                  styles.item,
                  selectedIndex === index ? styles.active : undefined,
                )}
                data-index={index}
              >
                <Link
                  to={logUrl(file.name, logs.log_dir)}
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
