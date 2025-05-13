import { FC, memo, RefObject, useMemo } from "react";
import { Events } from "../../../@types/log";
import { TranscriptVirtualListComponent } from "./TranscriptVirtualListComponent";
import { fixupEventStream } from "./transform/fixups";
import { treeifyEvents } from "./transform/treeify";
//
import styles from "./TranscriptPanel.module.css";
import { TranscriptTree } from "./TranscriptTree";

interface TranscriptPanelProps {
  id: string;
  events: Events;
  depth?: number;
  scrollRef: RefObject<HTMLDivElement | null>;
  running?: boolean;
  initialEventId?: string | null;
}

/**
 * Renders the Transcript Virtual List.
 */
export const TranscriptPanel: FC<TranscriptPanelProps> = memo((props) => {
  let { id, scrollRef, events, depth, running, initialEventId } = props;

  // Normalize Events themselves
  const eventNodes = useMemo(() => {
    const resolvedEvents = fixupEventStream(events, !running);
    const eventNodes = treeifyEvents(resolvedEvents, depth || 0);

    return eventNodes;
  }, [events, depth]);

  return (
    <div className={styles.container}>
      <div className={styles.treeContainer}>
        <TranscriptTree eventNodes={eventNodes} />
      </div>
      <TranscriptVirtualListComponent
        id={id}
        eventNodes={eventNodes}
        scrollRef={scrollRef}
        running={running}
        initialEventId={initialEventId}
      />
    </div>
  );
});
