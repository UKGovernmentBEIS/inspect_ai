import clsx from "clsx";
import {
  ReactNode,
  RefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { Components, Virtuoso, VirtuosoHandle } from "react-virtuoso";
import { usePrevious, useProperty } from "../state/hooks";
import { useRafThrottle, useVirtuosoState } from "../state/scrolling";
import { PulsingDots } from "./PulsingDots";

import styles from "./LiveVirtualList.module.css";

interface LiveVirtualListProps<T> {
  id: string;
  className?: string | string[];

  // The scroll ref to use for the virtual list
  scrollRef?: RefObject<HTMLDivElement | null>;

  // The data and rendering function for the data
  data: T[];
  renderRow: (index: number, item: T) => ReactNode;

  // Whether the virtual list is live (controls its follow
  // behavior)
  live?: boolean;

  // The progress message to show (if any)
  // no message show if progress isn't provided
  showProgress?: boolean;

  // The initial index to scroll to when loading
  initialTopMostItemIndex?: number;

  // The offset to use when scrolling items
  offsetTop?: number;

  components?: Components<T>;
}

/**
 * Renders the Transcript component.
 */
export const LiveVirtualList = <T,>({
  id,
  className,
  data,
  renderRow,
  scrollRef,
  live,
  showProgress,
  initialTopMostItemIndex,
  offsetTop,
  components,
}: LiveVirtualListProps<T>) => {
  // The list handle and list state management
  const listHandle = useRef<VirtuosoHandle>(null);
  const { getRestoreState, isScrolling } = useVirtuosoState(
    listHandle,
    `live-virtual-list-${id}`,
  );

  // Track whether we're following output
  const [followOutput, setFollowOutput] = useProperty<boolean | null>(
    id,
    "follow",
    {
      defaultValue: null,
    },
  );
  const isAutoScrollingRef = useRef(false);

  // Only we first load set the default value for following
  // based upon whether or not the transcript is 'live'
  useEffect(() => {
    if (followOutput === null) {
      setFollowOutput(!!live);
    }
  }, []);

  // Track whether we were previously running so we can
  // decide whether to pop up to the top
  const prevLive = usePrevious(live);
  useEffect(() => {
    // When we finish running, if we are following output
    // then scroll up to the top
    if (!live && prevLive && followOutput && scrollRef?.current) {
      setFollowOutput(false);
      setTimeout(() => {
        if (scrollRef.current) {
          scrollRef.current.scrollTo({ top: 0, behavior: "instant" });
        }
      }, 100);
    }
  }, [live, followOutput]);

  const handleScroll = useRafThrottle(() => {
    // Skip processing if auto-scrolling is in progress
    if (isAutoScrollingRef.current) return;

    // If we're not running, don't mess with auto scrolling
    if (!live) return;

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
  }, [setFollowOutput, followOutput, live]);

  const heightChanged = useCallback(
    (height: number) => {
      requestAnimationFrame(() => {
        if (followOutput && live && scrollRef?.current) {
          isAutoScrollingRef.current = true;
          listHandle.current?.scrollTo({ top: height });
          requestAnimationFrame(() => {
            isAutoScrollingRef.current = false;
          });
        }
      });
    },
    [scrollRef, followOutput, live],
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

  const Footer = () => {
    return showProgress ? (
      <div className={clsx(styles.progressContainer)}>
        <PulsingDots subtle={false} size="medium" />
      </div>
    ) : undefined;
  };

  useEffect(() => {
    // Listen to scroll events
    const parent = scrollRef?.current;
    if (parent) {
      parent.addEventListener("scroll", handleScroll);
      return () => parent.removeEventListener("scroll", handleScroll);
    }
  }, [scrollRef, handleScroll]);

  // Scroll to index when component mounts or targetIndex changes
  useEffect(() => {
    if (initialTopMostItemIndex !== undefined && listHandle.current) {
      // If there is an initial index, scroll to it after a short delay
      const timer = setTimeout(() => {
        listHandle.current?.scrollToIndex({
          index: initialTopMostItemIndex,
          align: "start",
          behavior: "smooth",
          offset: offsetTop ? -offsetTop : undefined,
        });
      }, 50);

      return () => clearTimeout(timer);
    }
  }, [initialTopMostItemIndex]);

  return (
    <Virtuoso
      ref={listHandle}
      customScrollParent={scrollRef?.current ? scrollRef.current : undefined}
      style={{ height: "100%", width: "100%" }}
      data={data}
      defaultItemHeight={250}
      itemContent={renderRow}
      increaseViewportBy={{ top: 1000, bottom: 1000 }}
      overscan={{ main: 2, reverse: 2 }}
      className={clsx("transcript", className)}
      isScrolling={isScrolling}
      restoreStateFrom={getRestoreState()}
      totalListHeightChanged={heightChanged}
      components={{
        Footer,
        ...components,
      }}
    />
  );
};
