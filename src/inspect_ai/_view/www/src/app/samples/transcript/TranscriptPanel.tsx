import { FC, memo, RefObject } from "react";
import { Events } from "../../../@types/log";
import { StickyScroll } from "../../../components/StickyScroll";
import { TranscriptOutline } from "./TranscriptOutline";
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

  return (
    <div className={styles.container}>
      <StickyScroll
        scrollRef={scrollRef}
        className={styles.treeContainer}
        offsetTop={topOffset}
      >
        <TranscriptOutline
          className={styles.outline}
          eventNodes={eventNodes}
          defaultCollapsedIds={defaultCollapsedIds}
        />
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
