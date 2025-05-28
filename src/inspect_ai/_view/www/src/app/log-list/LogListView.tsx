import { FC, useCallback } from "react";

import { clsx } from "clsx";
import { Virtuoso } from "react-virtuoso";
import { useStore } from "../../state/store";
import { FileLogItem, FolderLogItem } from "./LogItem";

import { Link } from "react-router-dom";
import { toDisplayScorers } from "../../scoring/metrics";
import { groupScorers } from "../../scoring/scores";
import { ApplicationIcons } from "../appearance/icons";
import { ScoreGrid } from "../log-view/title-view/ScoreGrid";
import styles from "./LogListView.module.css";

interface LogListViewProps {
  items: (FileLogItem | FolderLogItem)[];
  className?: string | string[];
}

export const LogListView: FC<LogListViewProps> = ({ items, className }) => {
  const renderRow = useCallback(
    (_index: number, item: FileLogItem | FolderLogItem) => {
      return <LogListRow item={item} />;
    },
    [],
  );

  return (
    <Virtuoso<FileLogItem | FolderLogItem>
      style={{ height: "100%" }}
      data={items}
      defaultItemHeight={50}
      itemContent={renderRow}
      atBottomThreshold={30}
      increaseViewportBy={{ top: 300, bottom: 300 }}
      overscan={{
        main: 10,
        reverse: 10,
      }}
      className={clsx(className, "samples-list")}
      skipAnimationFrameInResizeObserver={true}
      tabIndex={0}
    />
  );
};

interface LogListRowProps {
  item: FileLogItem | FolderLogItem;
}

const LogListRow: FC<LogListRowProps> = ({ item }) => {
  const fileItem = item.type === "file" ? item : undefined;

  const headerInfo = useStore(
    (state) => state.logs.logHeaders[fileItem?.logFile.name || ""],
  );
  const completed = headerInfo?.stats?.completed_at;
  const time = completed ? new Date(completed) : undefined;
  const timeStr = time
    ? `${time.toDateString()}
    ${time.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    })}`
    : "";

  const scorers = headerInfo?.results?.scores || [];
  const grouped = groupScorers(toDisplayScorers(scorers));

  let primaryResults = grouped.length > 0 ? grouped[0] : [];
  if (primaryResults.length > 3) {
    const shorterResults = grouped.find((g) => {
      return g.length <= 3;
    });
    if (shorterResults) {
      primaryResults = shorterResults;
    }

    // If the primary metrics are still too long, truncate them and
    // show the rest in the modal
    if (primaryResults.length > 3) {
      primaryResults = primaryResults.slice(0, 3);
    }
  }

  return (
    <div className={clsx(styles.row)}>
      <div className={clsx(styles.left)}>
        <div className={clsx(styles.icon)}>
          <i
            className={clsx(
              item.type === "file"
                ? ApplicationIcons.file
                : ApplicationIcons.folder,
            )}
          />
        </div>
        <div className={clsx(styles.task, "text-size-base")}>
          {item.url ? (
            <Link to={item.url}>
              {fileItem?.logFile ? headerInfo?.eval.task : item.name}
            </Link>
          ) : fileItem?.logFile ? (
            headerInfo?.eval.task
          ) : (
            item.name
          )}
        </div>
        <div className={clsx(styles.taskDetail)}>
          <div className={clsx("text-size-smallest")}>{timeStr}</div>
          <div className={clsx("text-size-smallest")}>
            {fileItem?.logFile ? headerInfo?.eval.model : undefined}
          </div>
        </div>
      </div>
      <div className={clsx(styles.right)}>
        {item.type === "file" ? (
          primaryResults.length && <ScoreGrid scoreGroups={[primaryResults]} />
        ) : (
          <div className={clsx(styles.folderItems)}>{item.itemCount} logs</div>
        )}
      </div>
    </div>
  );
};
