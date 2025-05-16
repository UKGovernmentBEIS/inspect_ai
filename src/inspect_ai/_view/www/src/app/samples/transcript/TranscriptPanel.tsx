import { FC, memo, RefObject } from "react";
import { Events } from "../../../@types/log";
import { StickyScroll } from "../../../components/StickyScroll";
import { TranscriptOutline } from "./TranscriptOutline";
import styles from "./TranscriptPanel.module.css";
import { TranscriptVirtualList } from "./TranscriptVirtualList";
import { useEventNodes } from "./transform/hooks";

const kSampleTabOffset = 31;

interface TranscriptPanelProps {
  id: string;
  events: Events;
  scrollRef: RefObject<HTMLDivElement | null>;
  running?: boolean;
  initialEventId?: string | null;
}

/**
 * Renders the Transcript Virtual List.
 */
export const TranscriptPanel: FC<TranscriptPanelProps> = memo((props) => {
  let { id, scrollRef, events, running, initialEventId } = props;

  const { eventNodes, defaultCollapsedIds } = useEventNodes(
    events,
    running === true,
  );

  return (
    <div className={styles.container}>
      <StickyScroll
        scrollRef={scrollRef}
        className={styles.treeContainer}
        offsetTop={kSampleTabOffset}
      >
        <TranscriptOutline
          scrollRef={scrollRef}
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
        offsetTop={kSampleTabOffset}
        className={styles.listContainer}
      />
    </div>
  );
});
