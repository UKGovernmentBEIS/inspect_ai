import clsx from "clsx";
import { JSX, useState } from "react";
import { ApplicationIcons } from "../app/appearance/icons";
import { useStore } from "../state/store";
import styles from "./DownloadLogButton.module.css";

type DownloadState = "idle" | "downloading" | "success" | "error";

interface DownloadLogButtonProps {
  log_file: string;
  className?: string;
  ariaLabel?: string;
}

export const DownloadLogButton = ({
  log_file,
  className = "",
  ariaLabel = "Download log as EVAL",
}: DownloadLogButtonProps): JSX.Element => {
  const [downloadState, setDownloadState] = useState<DownloadState>("idle");
  const api = useStore((state) => state.api);

  const handleClick = async (): Promise<void> => {
    if (!api?.download_log) return;

    setDownloadState("downloading");

    try {
      await api.download_log(log_file);
      setDownloadState("success");
    } catch (error) {
      console.error("Failed to download log:", error);
      setDownloadState("error");
    } finally {
      setTimeout(() => {
        setDownloadState("idle");
      }, 1250);
    }
  };

  const getIcon = (): string => {
    switch (downloadState) {
      case "downloading":
        return ApplicationIcons.loading;
      case "success":
        return ApplicationIcons.confirm;
      case "error":
        return ApplicationIcons.error;
      default:
        return ApplicationIcons.downloadLog;
    }
  };

  const getIconClass = (): string => {
    const icon = getIcon();
    if (downloadState === "success") {
      return `${icon} primary`;
    }
    if (downloadState === "error") {
      return `${icon} text-danger`;
    }
    return icon;
  };

  return (
    <button
      type="button"
      className={clsx(
        "download-log-button",
        styles.downloadLogButton,
        className,
      )}
      onClick={handleClick}
      aria-label={ariaLabel}
      disabled={downloadState !== "idle"}
    >
      <i className={getIconClass()} aria-hidden="true" />
    </button>
  );
};
