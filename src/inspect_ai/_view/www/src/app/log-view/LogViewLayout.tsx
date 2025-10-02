import clsx from "clsx";
import { FC, useEffect, useRef } from "react";
import { ActivityBar } from "../../components/ActivityBar";
import { ErrorPanel } from "../../components/ErrorPanel";
import { ExtendedFindProvider } from "../../components/ExtendedFindContext";
import { FindBand } from "../../components/FindBand";
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

  // Global keydown handler for keyboard shortcuts
  useEffect(() => {
    const handleGlobalKeyDown = (e: globalThis.KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        e.preventDefault(); // Always prevent browser find
        e.stopPropagation();
        if (setShowFind) {
          setShowFind(true);
        }
      } else if (e.key === "Escape") {
        hideFind();
      }
    };

    // Use capture phase to catch event before it reaches other handlers
    document.addEventListener("keydown", handleGlobalKeyDown, true);

    return () => {
      document.removeEventListener("keydown", handleGlobalKeyDown, true);
    };
  }, [setShowFind, hideFind]);

  return (
    <ExtendedFindProvider>
      <div
        ref={mainAppRef}
        className={clsx(
          "app-main-grid",
          fullScreen ? "full-screen" : undefined,
          singleFileMode ? "single-file-mode" : undefined,
          "log-view",
        )}
        tabIndex={0}
      >
        {showFind ? <FindBand /> : ""}
        {!singleFileMode ? <Navbar /> : ""}
        <ActivityBar animating={appStatus.loading} />
        {appStatus.error ? (
          <ErrorPanel
            title="An error occurred while loading this task."
            error={appStatus.error}
          />
        ) : (
          <LogView />
        )}
      </div>
    </ExtendedFindProvider>
  );
};
