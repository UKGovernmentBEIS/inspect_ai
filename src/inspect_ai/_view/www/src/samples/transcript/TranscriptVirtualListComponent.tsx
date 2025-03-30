import clsx from "clsx";
import { FC, RefObject, useCallback } from "react";
import { RenderedEventNode } from "./TranscriptView";
import { EventNode } from "./types";

import { LiveVirtualList } from "../../components/LiveVirtualList";
import styles from "./TranscriptVirtualListComponent.module.css";

interface TranscriptVirtualListComponentProps {
  id: string;
  eventNodes: EventNode[];
  scrollRef?: RefObject<HTMLDivElement | null>;
  running?: boolean;
}

/**
 * Renders the Transcript component.
 */
export const TranscriptVirtualListComponent: FC<
  TranscriptVirtualListComponentProps
> = ({ id, eventNodes, scrollRef, running }) => {
  const renderRow = useCallback((index: number, item: EventNode) => {
    const bgClass = item.depth % 2 == 0 ? styles.darkenedBg : styles.normalBg;
    const paddingClass = index === 0 ? styles.first : undefined;

    const eventId = `${id}-event-${index}`;

    return (
      <div key={eventId} className={clsx(styles.node, paddingClass)}>
        <RenderedEventNode id={eventId} node={item} className={clsx(bgClass)} />
      </div>
    );
  }, []);

  return (
    <LiveVirtualList<EventNode>
      id={id}
      scrollRef={scrollRef}
      data={eventNodes}
      renderRow={renderRow}
      live={running}
    />
  );
};
