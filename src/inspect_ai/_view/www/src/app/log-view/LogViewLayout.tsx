import clsx from "clsx";
import { FC, KeyboardEvent, useCallback, useRef } from "react";
import { ErrorPanel } from "../../components/ErrorPanel";
import { FindBand } from "../../components/FindBand";
import { ProgressBar } from "../../components/ProgressBar";
import { useStore } from "../../state/store";
import { Sidebar } from "../sidebar/Sidebar";
import { LogView } from "./LogView";

/**
 * AppContent component with the main UI layout
 */
export const LogViewLayout: FC = () => {
  // App layout and state
  const appStatus = useStore((state) => state.app.status);
  const offCanvas = useStore((state) => state.app.offcanvas);
  const setOffCanvas = useStore((state) => state.appActions.setOffcanvas);
  const clearWorkspaceTab = useStore(
    (state) => state.appActions.clearWorkspaceTab,
  );
  const clearSampleTab = useStore((state) => state.appActions.clearSampleTab);

  // Find
  const nativeFind = useStore((state) => state.capabilities.nativeFind);
  const showFind = useStore((state) => state.app.showFind);
  const setShowFind = useStore((state) => state.appActions.setShowFind);
  const hideFind = useStore((state) => state.appActions.hideFind);

  // Logs Data
  const logs = useStore((state) => state.logs.logs);
  const selectedLogIndex = useStore((state) => state.logs.selectedLogIndex);
  const logHeaders = useStore((state) => state.logs.logHeaders);
  const headersLoading = useStore((state) => state.logs.headersLoading);

  // Log Data
  const selectedLogSummary = useStore((state) => state.log.selectedLogSummary);
  const resetFiltering = useStore((state) => state.logActions.resetFiltering);
  const selectSample = useStore((state) => state.logActions.selectSample);

  // The main application reference
  const mainAppRef = useRef<HTMLDivElement>(null);

  // Configure an app envelope specific to the current state
  // if there are no log files, then don't show sidebar
  const fullScreen = logs.files.length === 1 && !logs.log_dir;

  const handleSelectedIndexChanged = useCallback(() => {
    setOffCanvas(false);
    resetFiltering();
    clearSampleTab();
    clearWorkspaceTab();
  }, [
    setOffCanvas,
    resetFiltering,
    clearSampleTab,
    clearWorkspaceTab,
    selectSample,
  ]);

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
      {!fullScreen && selectedLogSummary ? (
        <Sidebar
          logHeaders={logHeaders}
          loading={headersLoading}
          selectedIndex={selectedLogIndex}
          onSelectedIndexChanged={handleSelectedIndexChanged}
        />
      ) : undefined}
      <div
        ref={mainAppRef}
        className={clsx(
          "app-main-grid",
          fullScreen ? "full-screen" : undefined,
          offCanvas ? "off-canvas" : undefined,
        )}
        tabIndex={0}
        onKeyDown={handleKeyboard}
      >
        {!nativeFind && showFind ? <FindBand /> : ""}
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
