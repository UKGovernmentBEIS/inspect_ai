import clsx from "clsx";
import { FC, memo, RefObject } from "react";
import { useParams } from "react-router-dom";
import { Events } from "../../../@types/log";
import { StickyScroll } from "../../../components/StickyScroll";
import { useCollapsedState } from "../../../state/hooks";
import { ApplicationIcons } from "../../appearance/icons";
import { TranscriptOutline } from "./outline/TranscriptOutline";
import styles from "./TranscriptPanel.module.css";
import { TranscriptVirtualList } from "./TranscriptVirtualList";
import { useEventNodes } from "./transform/hooks";

interface TranscriptPanelProps {
  id: string;
  events: Events;
  scrollRef: RefObject<HTMLDivElement | null>;
  running?: boolean;
  initialEventId?: string | null;
  topOffset?: number;
}

/**
 * Renders the Transcript Virtual List.
 */
export const TranscriptPanel: FC<TranscriptPanelProps> = memo((props) => {
  let { id, scrollRef, events, running, initialEventId, topOffset } = props;

  const { eventNodes, defaultCollapsedIds } = useEventNodes(
    events,
    running === true,
  );
  const { logPath } = useParams<{ logPath: string }>();

  const [collapsed, setCollapsed] = useCollapsedState(
    `transcript-panel-${logPath || "na"}`,
    false,
  );

  return (
    <div
      className={clsx(
        styles.container,
        collapsed ? styles.collapsed : undefined,
      )}
    >
      <StickyScroll
        scrollRef={scrollRef}
        className={styles.treeContainer}
        offsetTop={topOffset}
      >
        <TranscriptOutline
          className={clsx(styles.outline)}
          eventNodes={eventNodes}
          running={running}
          defaultCollapsedIds={defaultCollapsedIds}
          scrollRef={scrollRef}
        />
        <div
          className={styles.outlineToggle}
          onClick={() => setCollapsed(!collapsed)}
        >
          <i className={ApplicationIcons.sidebar} />
        </div>
      </StickyScroll>
      <TranscriptVirtualList
        id={id}
        eventNodes={eventNodes}
        defaultCollapsedIds={defaultCollapsedIds}
        scrollRef={scrollRef}
        running={running}
        initialEventId={initialEventId === undefined ? null : initialEventId}
        offsetTop={topOffset}
        className={styles.listContainer}
      />
    </div>
  );
});
