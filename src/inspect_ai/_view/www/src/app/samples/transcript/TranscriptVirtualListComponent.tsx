import clsx from "clsx";
import { FC, RefObject, useCallback, useMemo } from "react";
import { RenderedEventNode } from "./TranscriptVirtualList";
import { EventNode } from "./types";

import { VirtuosoHandle } from "react-virtuoso";
import { LiveVirtualList } from "../../../components/LiveVirtualList";
import styles from "./TranscriptVirtualListComponent.module.css";

interface TranscriptVirtualListComponentProps {
  id: string;
  listHandle: RefObject<VirtuosoHandle | null>;
  eventNodes: EventNode[];
  initialEventId?: string | null;
  offsetTop?: number;
  scrollRef?: RefObject<HTMLDivElement | null>;
  running?: boolean;
  className?: string | string[];
}

/**
 * Renders the Transcript component.
 */
export const TranscriptVirtualListComponent: FC<
  TranscriptVirtualListComponentProps
> = ({
  id,
  listHandle,
  eventNodes,
  scrollRef,
  running,
  initialEventId,
  offsetTop,
  className,
}) => {
  const initialEventIndex = useMemo(() => {
    if (initialEventId === null || initialEventId === undefined) {
      return undefined;
    }
    const result = eventNodes.findIndex((event) => {
      return event.id === initialEventId;
    });
    return result === -1 ? undefined : result;
  }, [initialEventId, eventNodes]);

  const hasToolEventsAtCurrentDepth = useCallback(
    (startIndex: number) => {
      // Walk backwards from this index to see if we see any tool events
      // at this depth, prior to this event
      for (let i = startIndex; i >= 0; i--) {
        const node = eventNodes[i];
        if (node.event.event === "tool") {
          return true;
        }
        if (node.depth < eventNodes[startIndex].depth) {
          return false;
        }
      }
      return false;
    },
    [eventNodes],
  );

  const contextWithToolEvents = useMemo(() => ({ hasToolEvents: true }), []);
  const contextWithoutToolEvents = useMemo(
    () => ({ hasToolEvents: false }),
    [],
  );

  const renderRow = useCallback(
    (index: number, item: EventNode) => {
      const paddingClass = index === 0 ? styles.first : undefined;

      const previousIndex = index - 1;
      const nextIndex = index + 1;
      const previous =
        previousIndex > 0 && previousIndex <= eventNodes.length
          ? eventNodes[previousIndex]
          : undefined;
      const next =
        nextIndex < eventNodes.length ? eventNodes[nextIndex] : undefined;
      const attached =
        item.event.event === "tool" &&
        (previous?.event.event === "tool" || previous?.event.event === "model");

      const attachedParent =
        item.event.event === "model" && next?.event.event === "tool";
      const attachedClass = attached ? styles.attached : undefined;
      const attachedChildClass = attached ? styles.attachedChild : undefined;
      const attachedParentClass = attachedParent
        ? styles.attachedParent
        : undefined;

      const hasToolEvents = hasToolEventsAtCurrentDepth(index);
      const context = hasToolEvents
        ? contextWithToolEvents
        : contextWithoutToolEvents;

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
          <RenderedEventNode
            node={item}
            next={next}
            className={clsx(attachedParentClass, attachedChildClass)}
            context={context}
          />
        </div>
      );
    },
    [
      eventNodes,
      hasToolEventsAtCurrentDepth,
      contextWithToolEvents,
      contextWithoutToolEvents,
    ],
  );

  return (
    <LiveVirtualList<EventNode>
      listHandle={listHandle}
      className={className}
      id={id}
      scrollRef={scrollRef}
      data={eventNodes}
      initialTopMostItemIndex={initialEventIndex}
      offsetTop={offsetTop}
      renderRow={renderRow}
      live={running}
    />
  );
};
