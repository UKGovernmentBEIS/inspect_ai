import { FC, useState, useEffect } from "react";
import { PopOver } from "../../components/PopOver";
import { useStore } from "../../state/store";
import { DB_VERSION } from "../../client/database/schema";

import clsx from "clsx";
import styles from "./ViewerOptionsPopover.module.css";

// Version info injected at build time
declare const __VIEWER_VERSION__: string;
declare const __VIEWER_COMMIT__: string;

export interface ViewerOptionsPopoverProps {
  showing: boolean;
  setShowing: (showing: boolean) => void;
  positionEl: HTMLElement | null;
}

interface DatabaseStats {
  logFiles: number;
  logSummaries: number;
  logInfo: number;
  logDir: string | null;
}

export const ViewerOptionsPopover: FC<ViewerOptionsPopoverProps> = ({
  showing,
  positionEl,
  setShowing,
}) => {
  const [isClearing, setIsClearing] = useState(false);
  const [clearMessage, setClearMessage] = useState<string | null>(null);
  const [dbStats, setDbStats] = useState<DatabaseStats | null>(null);
  const databaseService = useStore((state) => state.databaseService);

  useEffect(() => {
    const loadStats = async () => {
      if (!databaseService || !showing) return;

      try {
        const stats = await databaseService.getCacheStats();
        setDbStats({
          logFiles: stats.logFiles,
          logSummaries: stats.logSummaries,
          logInfo: stats.logHeaders,
          logDir: stats.logDir,
        });
      } catch (error) {
        console.error("Failed to load database stats:", error);
        setDbStats(null);
      }
    };

    loadStats();
  }, [databaseService, showing]);

  const handleClearDatabase = async () => {
    if (!databaseService) {
      setClearMessage("Database service not available");
      setTimeout(() => setClearMessage(null), 3000);
      return;
    }

    setIsClearing(true);
    setClearMessage(null);

    try {
      await databaseService.clearAllCaches();
      setClearMessage("Database cleared successfully");
      // Refresh stats after clearing
      setDbStats({
        logFiles: 0,
        logSummaries: 0,
        logInfo: 0,
        logDir: dbStats?.logDir || null,
      });
      setTimeout(() => setClearMessage(null), 3000);
    } catch (error) {
      console.error("Failed to clear database:", error);
      setClearMessage("Failed to clear database");
      setTimeout(() => setClearMessage(null), 3000);
    } finally {
      setIsClearing(false);
    }
  };

  return (
    <PopOver
      id={`viewer-options-filter-popover`}
      positionEl={positionEl}
      isOpen={showing}
      setIsOpen={setShowing}
      placement="auto"
      hoverDelay={-1}
      offset={[-10, 5]}
      showArrow={false}
    >
      <div className={clsx(styles.container, "text-size-smaller")}>
        <b>Inspect Viewer</b>
        <div className={styles.content}>
          <div className={styles.statsSection}>
            <div className={styles.statRow}>
              <strong>Version:</strong> {__VIEWER_VERSION__}
            </div>
            <div className={styles.statRow}>
              <strong>Database Version:</strong> {DB_VERSION}
            </div>
            {dbStats && (
              <>
                <div className={styles.statRow}>
                  <strong>Log Directory:</strong>{" "}
                  {dbStats.logDir ? (
                    <span className={styles.logDir}>{dbStats.logDir}</span>
                  ) : (
                    <span className={styles.notSet}>Not set</span>
                  )}
                </div>
                <div className={styles.statRow}>
                  <strong>Cached Items:</strong>
                  <ul className={styles.cachedItemsList}>
                    <li>Log Files: {dbStats.logFiles}</li>
                    <li>Log Summaries: {dbStats.logSummaries}</li>
                    <li>Log Info: {dbStats.logInfo}</li>
                  </ul>
                </div>
              </>
            )}
          </div>
          <button
            onClick={handleClearDatabase}
            disabled={isClearing}
            className={clsx(
              "btn",
              "btn-tools",
              "text-size-smaller",
              styles.clearButton,
            )}
          >
            {isClearing ? "Clearing..." : "Clear Local Database"}
          </button>
          {clearMessage && (
            <div
              className={clsx(
                styles.message,
                clearMessage.includes("success")
                  ? styles.messageSuccess
                  : styles.messageError,
              )}
            >
              {clearMessage}
            </div>
          )}
        </div>
      </div>
    </PopOver>
  );
};
