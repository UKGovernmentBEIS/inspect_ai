import clsx from "clsx";
import { FC, RefObject, useRef } from "react";
import { Virtuoso, VirtuosoHandle } from "react-virtuoso";
import { RenderedEventNode } from "./TranscriptView";
import { EventNode } from "./types";

import { useProperty } from "../../state/hooks";
import { useVirtuosoState } from "../../state/scrolling";
import styles from "./TranscriptVirtualListComponent.module.css";

interface TranscriptVirtualListComponentProps {
  id: string;
  eventNodes: EventNode[];
  scrollRef?: RefObject<HTMLDivElement | null>;
}

/**
 * Renders the Transcript component.
 */
export const TranscriptVirtualListComponent: FC<
  TranscriptVirtualListComponentProps
> = ({ id, eventNodes, scrollRef }) => {
  const listHandle = useRef<VirtuosoHandle>(null);
  const { restoreState, isScrolling } = useVirtuosoState(
    listHandle,
    "transcript",
  );

  const [followOutput, setFollowOutput] = useProperty(id, "follow", {
    defaultValue: false,
  });

  const renderRow = (item: EventNode, index: number) => {
    const bgClass = item.depth % 2 == 0 ? styles.darkenedBg : styles.normalBg;
    const paddingClass = index === 0 ? styles.first : undefined;

    const eventId = `${id}-event${index}`;

    return (
      <div key={eventId} className={clsx(styles.node, paddingClass)}>
        <RenderedEventNode
          id={eventId}
          node={item}
          className={clsx(bgClass)}
          scrollRef={scrollRef}
        />
      </div>
    );
  };

  return (
    <Virtuoso
      ref={listHandle}
      customScrollParent={scrollRef?.current ? scrollRef.current : undefined}
      style={{ height: "100%", width: "100%" }}
      data={eventNodes}
      itemContent={(index: number, data: EventNode) => {
        return renderRow(data, index);
      }}
      increaseViewportBy={{ top: 1000, bottom: 1000 }}
      overscan={{
        main: 10,
        reverse: 10,
      }}
      followOutput={followOutput}
      atBottomStateChange={(atBottom: boolean) => {
        setFollowOutput(atBottom);
      }}
      skipAnimationFrameInResizeObserver={true}
      className={clsx("transcript")}
      isScrolling={isScrolling}
      restoreStateFrom={restoreState()}
    />
  );
};
