import clsx from "clsx";
import { FC, useEffect, useMemo } from "react";

import { Link, useParams } from "react-router-dom";
import { ProgressBar } from "../../components/ProgressBar";
import { useLogs } from "../../state/hooks";
import { useStore } from "../../state/store";
import { basename, dirname } from "../../utils/path";
import { directoryRelativeUrl, join } from "../../utils/uri";
import { ApplicationIcons } from "../appearance/icons";
import { logUrl } from "../routing/url";
import { LogItem } from "./LogItem";
import { LogListFooter } from "./LogListFooter";
import styles from "./LogListView.module.css";
import { LogsHeader } from "./LogsHeader";

const rootName = (relativePath: string) => {
  const parts = relativePath.split("/");
  if (parts.length === 0) {
    return "";
  }
  return parts[0];
};

interface LogListViewProps {}

export const LogListView: FC<LogListViewProps> = () => {
  // Get the logs from the store
  const loading = useStore((state) => state.app.status.loading);

  const { loadLogs } = useLogs();
  const logs = useStore((state) => state.logs.logs);

  const { logPath } = useParams<{
    logPath?: string;
    tabId?: string;
    sampleId?: string;
    epoch?: string;
  }>();

  const currentDir = join(decodeURIComponent(logPath || ""), logs.log_dir);
  const baseLogDir = dirname(logs.log_dir || "");
  const baseLogName = basename(logs.log_dir || "");
  const pathSegments = logPath
    ? decodeURIComponent(logPath).split("/")
    : undefined;

  const dirSegments = pathSegments
    ? pathSegments.map((segment) => {
        return {
          text: segment,
          url: logUrl(segment, logs.log_dir),
        };
      })
    : [];

  const segments: Array<{ text: string; url?: string }> = [
    { text: baseLogDir },
    { text: baseLogName, url: logUrl("", logs.log_dir) },
    ...dirSegments,
  ];

  const logItems: LogItem[] = useMemo(() => {
    const itemNames: string[] = [];
    for (const logFile of logs.files) {
      const name = logFile.name;
      if (name.startsWith(currentDir)) {
        const relativePath = directoryRelativeUrl(name, currentDir);

        const root = rootName(relativePath);
        itemNames.push(decodeURIComponent(root));
      }
    }

    const items = new Set(itemNames);

    const result: LogItem[] = [];
    for (const item of items) {
      result.push({
        id: item,
        name: item,
        type:
          item.endsWith(".json") || item.endsWith(".eval") ? "file" : "folder",
        url: logUrl(item, currentDir),
      });
    }
    return result;
  }, [logPath, logs.files]);

  useEffect(() => {
    const exec = async () => {
      await loadLogs();
    };
    exec();
  }, [loadLogs]);

  return (
    <div className={clsx(styles.panel)}>
      <LogsHeader segments={segments} />
      <ProgressBar animating={loading} />
      <div className={clsx(styles.list)}>
        {logItems.map((logItem) => (
          <LogsRow item={logItem} />
        ))}
      </div>
      <LogListFooter itemCount={logItems.length} running={loading} />
    </div>
  );
};

interface LogsRowProps {
  item: LogItem;
}

export const LogsRow: FC<LogsRowProps> = ({ item }) => {
  return (
    <>
      <div>
        <i
          className={clsx(
            item.type === "file"
              ? ApplicationIcons.file
              : ApplicationIcons.folder,
          )}
        />
      </div>
      <div>{item.url ? <Link to={item.url}>{item.name}</Link> : item.name}</div>
    </>
  );
};
