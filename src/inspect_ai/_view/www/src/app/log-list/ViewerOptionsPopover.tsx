import { FC, useState } from "react";
import { DB_VERSION } from "../../client/database/schema";
import { PopOver } from "../../components/PopOver";
import { useStore } from "../../state/store";

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

export const ViewerOptionsPopover: FC<ViewerOptionsPopoverProps> = ({
  showing,
  positionEl,
  setShowing,
}) => {
  const [isClearing, setIsClearing] = useState(false);
  const [clearMessage, setClearMessage] = useState<string | null>(null);
  const replicationService = useStore((state) => state.replicationService);
  const dbStats = useStore((state) => state.logs.dbStats);

  const logDir = useStore((state) => state.logs.logDir);

  const handleClearDatabase = async () => {
    if (!replicationService) {
      setClearMessage("Database service not available");
      setTimeout(() => setClearMessage(null), 3000);
      return;
    }

    setIsClearing(true);
    setClearMessage(null);

    try {
      await replicationService.clearData();
      setClearMessage("Database cleared successfully");
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
        <div
          className={clsx(
            "text-style-label",
            "text-style-secondary",
            styles.fullWidth,
          )}
        >
          Log Directory
        </div>
        <div className={clsx(styles.fullWidth, styles.fullWidthPadded)}>
          <span className={styles.logDir}>{logDir}</span>
        </div>

        <div className={clsx(styles.spacer)}></div>

        <div className={clsx("text-style-label", "text-style-secondary")}>
          Version
        </div>
        <div className={clsx()}>{__VIEWER_VERSION__}</div>

        <div className={clsx("text-style-label", "text-style-secondary")}>
          Schema
        </div>
        <div className={clsx()}>{DB_VERSION}</div>

        <div className={clsx(styles.spacer)}></div>

        <div className={clsx("text-style-label", "text-style-secondary")}>
          Logs
        </div>
        <div className={clsx()}>{dbStats?.logCount || 0}</div>

        <div className={clsx("text-style-label", "text-style-secondary")}>
          Log Previews
        </div>
        <div className={clsx()}>{dbStats?.previewCount || 0}</div>

        <div className={clsx("text-style-label", "text-style-secondary")}>
          Log Details
        </div>
        <div className={clsx()}>{dbStats?.detailsCount || 0}</div>

        <div className={clsx(styles.spacer)}></div>

        <div className={clsx("text-style-label", "text-style-secondary")}>
          Tools
        </div>
        <div className={clsx()}>
          {" "}
          <button
            onClick={handleClearDatabase}
            disabled={isClearing}
            className={clsx(
              "btn",
              "btn-tools",
              "text-size-smallest",
              styles.clearButton,
            )}
          >
            {isClearing ? "Clearing..." : "Clear Local Database"}
          </button>
        </div>

        {clearMessage && (
          <div
            className={clsx(
              styles.fullWidth,
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
    </PopOver>
  );
};
