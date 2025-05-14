import { FC, memo, RefObject, useRef } from "react";
import { Events } from "../../../@types/log";
import styles from "./TranscriptPanel.module.css";
import { TranscriptTree } from "./TranscriptTree";
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

  const navRef = useRef<HTMLDivElement>(null);

  return (
    <div className={styles.container}>
      <div className={styles.treeContainer} ref={navRef}>
        <TranscriptTree
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
      />
    </div>
  );
});
