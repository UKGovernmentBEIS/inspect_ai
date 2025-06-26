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
  const nativeFind = useStore((state) => state.capabilities.nativeFind);
  const showFind = useStore((state) => state.app.showFind);
  const setShowFind = useStore((state) => state.appActions.setShowFind);
  const hideFind = useStore((state) => state.appActions.hideFind);
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
      // Add keyboard shortcuts for find, if needed
      if (nativeFind || !setShowFind) {
        return;
      }

      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        setShowFind(true);
      } else if (e.key === "Escape") {
        hideFind();
      }
    },
    [nativeFind, setShowFind, hideFind],
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
        {!nativeFind && showFind ? <FindBand /> : ""}
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
