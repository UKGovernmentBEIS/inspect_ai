import { FC, memo, RefObject } from "react";
import { Events } from "../../../@types/log";
import { useStickyRef } from "../../../components/StickyRef";
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

  const stickElement = useStickyRef({ scrollRef, enableSmoothing: false });

  return (
    <div className={styles.container}>
      <div
        className={styles.treeContainer}
        ref={stickElement.ref}
        style={stickElement.style}
      >
        <TranscriptOutline
          scrollRef={scrollRef}
          eventNodes={eventNodes}
          defaultCollapsedIds={defaultCollapsedIds}
        />
      </div>
      <TranscriptVirtualList
        id={id}
        eventNodes={eventNodes}
        defaultCollapsedIds={defaultCollapsedIds}
        scrollRef={scrollRef}
        running={running}
        initialEventId={initialEventId === undefined ? null : initialEventId}
        className={styles.listContainer}
      />
    </div>
  );
});
