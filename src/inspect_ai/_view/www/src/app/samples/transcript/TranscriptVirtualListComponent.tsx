import clsx from "clsx";
import { FC, RefObject, useCallback, useMemo } from "react";
import { RenderedEventNode } from "./TranscriptVirtualList";
import { EventNode } from "./types";

import { LiveVirtualList } from "../../../components/LiveVirtualList";
import styles from "./TranscriptVirtualListComponent.module.css";

interface TranscriptVirtualListComponentProps {
  id: string;
  eventNodes: EventNode[];
  initialEventId?: string | null;
  scrollRef?: RefObject<HTMLDivElement | null>;
  running?: boolean;
  className?: string | string[];
}

/**
 * Renders the Transcript component.
 */
export const TranscriptVirtualListComponent: FC<
  TranscriptVirtualListComponentProps
> = ({ id, eventNodes, scrollRef, running, initialEventId, className }) => {
  const initialEventIndex = useMemo(() => {
    if (initialEventId === null || initialEventId === undefined) {
      return undefined;
    }
    const result = eventNodes.findIndex((event) => {
      return event.id === initialEventId;
    });
    return result === -1 ? undefined : result;
  }, [initialEventId, eventNodes]);

  const renderRow = useCallback(
    (index: number, item: EventNode) => {
      const paddingClass = index === 0 ? styles.first : undefined;

      const previousIndex = index - 1;
      const previous =
        previousIndex > 0 && previousIndex <= eventNodes.length
          ? eventNodes[previousIndex]
          : undefined;
      const attached =
        item.event.event === "tool" &&
        (previous?.event.event === "tool" || previous?.event.event === "model");
      const attachedClass = attached ? styles.attached : undefined;

      return (
        <div
          id={item.id}
          key={item.id}
          className={clsx(styles.node, paddingClass, attachedClass)}
          style={{
            paddingLeft: `${item.depth <= 1 ? item.depth * 0.7 : (0.7 + item.depth - 1) * 1}em`,
            paddingRight: `${item.depth === 0 ? undefined : ".7em"} `,
          }}
        >
          <RenderedEventNode node={item} />
        </div>
      );
    },
    [eventNodes],
  );

  return (
    <LiveVirtualList<EventNode>
      className={className}
      id={id}
      scrollRef={scrollRef}
      data={eventNodes}
      initialTopMostItemIndex={initialEventIndex}
      renderRow={renderRow}
      live={running}
    />
  );
};
