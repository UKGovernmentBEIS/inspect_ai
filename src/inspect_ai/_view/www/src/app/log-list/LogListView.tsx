import clsx from "clsx";
import { FC, useEffect, useMemo } from "react";

import { useParams } from "react-router-dom";
import { ProgressBar } from "../../components/ProgressBar";
import { useLogs, usePagination } from "../../state/hooks";
import { useStore } from "../../state/store";
import { directoryRelativeUrl, join } from "../../utils/uri";
import { Navbar } from "../navbar/Navbar";
import { logUrl } from "../routing/url";
import { LogItem } from "./LogItem";
import { LogListFooter } from "./LogListFooter";
import { LogListGrid } from "./LogListGrid";
import styles from "./LogListView.module.css";

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

  const { page, itemsPerPage } = usePagination(currentDir);

  const pageItems = useMemo(() => {
    const start = (page || 0) * itemsPerPage;
    const end = start + itemsPerPage;
    return logItems.slice(start, end);
  }, [logItems, page, itemsPerPage]);

  useEffect(() => {
    const exec = async () => {
      await loadLogs();
    };
    exec();
  }, [loadLogs]);

  return (
    <div className={clsx(styles.panel)}>
      <Navbar />
      <ProgressBar animating={loading} />
      <div className={clsx(styles.list, "text-size-smaller")}>
        <LogListGrid items={pageItems} />
      </div>
      <LogListFooter
        logDir={currentDir}
        itemCount={logItems.length}
        running={loading}
      />
    </div>
  );
};
