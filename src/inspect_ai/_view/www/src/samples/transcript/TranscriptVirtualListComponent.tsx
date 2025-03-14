import clsx from "clsx";
import { FC, RefObject, useCallback, useEffect, useRef, useState } from "react";
import { Virtuoso, VirtuosoHandle } from "react-virtuoso";
import { RenderedEventNode } from "./TranscriptView";
import { EventNode } from "./types";

import { useProperty } from "../../state/hooks";
import { useRafThrottle, useVirtuosoState } from "../../state/scrolling";
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
  // The list handle and list state management
  const listHandle = useRef<VirtuosoHandle>(null);
  const { getRestoreState, isScrolling } = useVirtuosoState(
    listHandle,
    `transcript-${id}`,
  );

  // Track whether we're following output
  const [followOutput, setFollowOutput] = useProperty(id, "follow", {
    defaultValue: running,
  });
  const isAutoScrollingRef = useRef(false);

  // Track whether we were previously running so we can
  // decide whether to pop up to the top
  const prevRunningRef = useRef(running);

  useEffect(() => {
    // When we finish running, if we are following output
    // then scroll up to the top
    if (
      !running &&
      prevRunningRef.current &&
      followOutput &&
      listHandle.current
    ) {
      setFollowOutput(false);
      setTimeout(() => {
        if (listHandle.current) {
          listHandle.current.scrollTo({ top: 0, behavior: "instant" });
        }
      }, 100);
    }
    prevRunningRef.current = running;
  }, [running, followOutput, listHandle]);

  const handleScroll = useRafThrottle(() => {
    // Skip processing if auto-scrolling is in progress
    if (isAutoScrollingRef.current) return;

    // If we're not running, don't mess with auto scrolling
    if (!running) return;

    // Make the bottom start following
    if (scrollRef?.current && listHandle.current) {
      const parent = scrollRef.current;
      const isAtBottom =
        parent.scrollHeight - parent.scrollTop <= parent.clientHeight + 30;

      if (isAtBottom && !followOutput) {
        setFollowOutput(true);
      } else if (!isAtBottom && followOutput) {
        setFollowOutput(false);
      }
    }
  }, [setFollowOutput, followOutput, running]);

  const heightChanged = useCallback(
    (height: number) => {
      requestAnimationFrame(() => {
        if (followOutput && running) {
          isAutoScrollingRef.current = true;
          listHandle.current?.scrollTo({ top: height });
          requestAnimationFrame(() => {
            isAutoScrollingRef.current = false;
          });
        }
      });
    },
    [scrollRef, followOutput, running],
  );

  useEffect(() => {
    // Force a re-render after initial mount
    // This is here only because in VScode, for some reason,
    // when this transcript is restored, the height isn't computed
    // properly on the first render. This basically gives it a second
    // change to compute the height and lay itself out.
    const timer = setTimeout(() => {
      forceUpdate();
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  const [, forceRender] = useState({});
  const forceUpdate = useCallback(() => forceRender({}), []);

  useEffect(() => {
    // Listen to scroll events
    const parent = scrollRef?.current;
    if (parent) {
      parent.addEventListener("scroll", handleScroll);
      return () => parent.removeEventListener("scroll", handleScroll);
    }
  }, [scrollRef, handleScroll]);

  const renderRow = useCallback((index: number, item: EventNode) => {
    const bgClass = item.depth % 2 == 0 ? styles.darkenedBg : styles.normalBg;
    const paddingClass = index === 0 ? styles.first : undefined;

    const eventId = `${id}-event${index}`;

    return (
      <div key={eventId} className={clsx(styles.node, paddingClass)}>
        <RenderedEventNode id={eventId} node={item} className={clsx(bgClass)} />
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
      restoreStateFrom={getRestoreState()}
      totalListHeightChanged={heightChanged}
    />
  );
};
