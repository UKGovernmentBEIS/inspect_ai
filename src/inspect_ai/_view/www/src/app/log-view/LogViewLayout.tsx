import clsx from "clsx";
import { FC, KeyboardEvent, useCallback, useRef } from "react";
import { ErrorPanel } from "../../components/ErrorPanel";
import { FindBand } from "../../components/FindBand";
import { ProgressBar } from "../../components/ProgressBar";
import { useStore } from "../../state/store";
import { Navbar } from "../navbar/Navbar";
import { LogView } from "./LogView";

/**
 * AppContent component with the main UI layout
 */
export const LogViewLayout: FC = () => {
  // App layout and state
  const appStatus = useStore((state) => state.app.status);

  // Find
  const showFind = useStore((state) => state.appActions.showFind);
  const hideFind = useStore((state) => state.appActions.hideFind);
  const isFindShowing = useStore((state) => state.app.find.showing);

  // Are displaying in single file mode
  const singleFileMode = useStore((state) => state.app.singleFileMode);

  // Logs Data
  const logs = useStore((state) => state.logs.logs);

  // The main application reference
  const mainAppRef = useRef<HTMLDivElement>(null);

  // Configure an app envelope specific to the current state
  // if there are no log files, then don't show sidebar
  const fullScreen = logs.files.length === 1 && !logs.log_dir;

  const handleKeyboard = useCallback(
    (e: KeyboardEvent) => {
      // Add keyboard shortcuts forßfind, if needed
      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        showFind();
        e.stopPropagation();
        e.preventDefault();
      } else if (e.key === "Escape") {
        hideFind();
        e.stopPropagation();
        e.preventDefault();
      }
    },
    [showFind, hideFind],
  );

  return (
    <>
      <div
        ref={mainAppRef}
        className={clsx(
          "app-main-grid",
          fullScreen ? "full-screen" : undefined,
          singleFileMode ? "single-file-mode" : undefined,
          "log-view",
        )}
        tabIndex={0}
        onKeyDown={handleKeyboard}
      >
        {isFindShowing ? <FindBand /> : ""}
        {!singleFileMode ? <Navbar /> : ""}
        <ProgressBar animating={appStatus.loading} />
        {appStatus.error ? (
          <ErrorPanel
            title="An error occurred while loading this task."
            error={appStatus.error}
          />
        ) : (
          <LogView />
        )}
      </div>
    </>
  );
};
