import clsx from "clsx";
import { FC, memo, RefObject, useCallback, useEffect, useRef } from "react";
import { Virtuoso, VirtuosoHandle } from "react-virtuoso";
import { RenderedEventNode } from "./TranscriptView";
import { EventNode } from "./types";

import { useProperty } from "../../state/hooks";
import { useVirtuosoState } from "../../state/scrolling";
import { debounce } from "../../utils/sync";
import { TranscriptLoadingPanel } from "./TranscriptLoadingPanel";
import styles from "./TranscriptVirtualListComponent.module.css";

interface TranscriptVirtualListComponentProps {
  id: string;
  eventNodes: EventNode[];
  scrollRef?: RefObject<HTMLDivElement | null>;
  tailOutput?: boolean;
}

/**
 * Renders the Transcript component.
 */
export const TranscriptVirtualListComponent: FC<TranscriptVirtualListComponentProps> =
  memo(({ id, eventNodes, scrollRef, tailOutput }) => {
    // The list handle and list state management
    const listHandle = useRef<VirtuosoHandle>(null);
    const { restoreState, isScrolling } = useVirtuosoState(
      listHandle,
      `transcript-${id}`,
    );

    // Track whether we're following output
    const [followOutput, setFollowOutput] = useProperty(id, "follow", {
      defaultValue: tailOutput,
    });
    const isAutoScrollingRef = useRef(false);

    const handleParentScroll = useCallback(
      debounce(
        () => {
          // Skip processing if auto-scrolling is in progress
          if (isAutoScrollingRef.current) return;

          // Make the bottom start following
          if (scrollRef?.current && listHandle.current) {
            const parent = scrollRef.current;
            const isAtBottom =
              parent.scrollHeight - parent.scrollTop <= parent.clientHeight + 5;

            if (isAtBottom && !followOutput) {
              setFollowOutput(true);
            } else if (!isAtBottom && followOutput) {
              setFollowOutput(false);
            }
          }
        },
        100,
        { leading: true, trailing: true },
      ),
      [scrollRef, setFollowOutput, followOutput],
    );

    const heightChanged = useCallback(() => {
      requestAnimationFrame(() => {
        if (followOutput) {
          isAutoScrollingRef.current = true;
          listHandle.current?.scrollToIndex({
            index: "LAST",
            align: "end",
          });
          requestAnimationFrame(() => {
            isAutoScrollingRef.current = false;
          });
        }
      });
    }, [scrollRef, listHandle.current]);

    useEffect(() => {
      // Listen to scroll events
      const parent = scrollRef?.current;
      if (parent) {
        parent.addEventListener("scroll", handleParentScroll);
        return () => parent.removeEventListener("scroll", handleParentScroll);
      }
    }, [scrollRef, handleParentScroll]);

    const renderRow = useCallback((index: number, item: EventNode) => {
      const bgClass = item.depth % 2 == 0 ? styles.darkenedBg : styles.normalBg;
      const paddingClass = index === 0 ? styles.first : undefined;

      const eventId = `${id}-event${index}`;

      return (
        <div key={eventId} className={clsx(styles.node, paddingClass)}>
          <RenderedEventNode
            id={eventId}
            node={item}
            className={clsx(bgClass)}
          />
        </div>
      );
    }, []);

    return (
      <Virtuoso
        ref={listHandle}
        customScrollParent={scrollRef?.current ? scrollRef.current : undefined}
        style={{ height: "100%", width: "100%" }}
        data={eventNodes}
        defaultItemHeight={250}
        itemContent={renderRow}
        increaseViewportBy={{ top: 1000, bottom: 1000 }}
        overscan={{ main: 2, reverse: 2 }}
        className={clsx("transcript")}
        isScrolling={isScrolling}
        restoreStateFrom={restoreState}
        totalListHeightChanged={heightChanged}
        components={{
          Footer: tailOutput ? TranscriptLoadingPanel : undefined,
        }}
      />
    );
  });
