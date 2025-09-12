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
import { ExtendedFindFn, useExtendedFind } from "./ExtendedFindContext";
import { PulsingDots } from "./PulsingDots";

import styles from "./LiveVirtualList.module.css";

interface LiveVirtualListProps<T> {
  id: string;
  listHandle: RefObject<VirtuosoHandle | null>;

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

  // Optional function to search within data items for text
  // If not provided, will use JSON.stringify as fallback
  searchInItem?: (item: T, searchTerm: string) => boolean;
}

/**
 * Renders the Transcript component.
 */
export const LiveVirtualList = <T,>({
  id,
  listHandle,
  className,
  data,
  renderRow,
  scrollRef,
  live,
  showProgress,
  initialTopMostItemIndex,
  offsetTop,
  components,
  searchInItem,
}: LiveVirtualListProps<T>) => {
  // The list handle and list state management
  const { getRestoreState, isScrolling, visibleRange, setVisibleRange } =
    useVirtuosoState(listHandle, `live-virtual-list-${id}`);

  // Search functionality
  const { registerVirtualList } = useExtendedFind();
  const pendingSearchCallback = useRef<(() => void) | null>(null);
  const [isCurrentlyScrolling, setIsCurrentlyScrolling] = useState(false);

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

  // Default search function that uses JSON.stringify as fallback
  const defaultSearchInItem = useCallback(
    (item: T, searchTerm: string): boolean => {
      const searchLower = searchTerm.toLowerCase();
      try {
        // TODO: should we make this more pluggable?
        const itemString = JSON.stringify(item).toLowerCase();
        return itemString.includes(searchLower);
      } catch {
        return false;
      }
    },
    [],
  );

  // Search in data function
  const searchInData: ExtendedFindFn = useCallback(
    async (
      term: string,
      direction: "forward" | "backward",
      onContentReady: () => void,
    ) => {
      if (!data.length || !term) return false;

      const searchFn = searchInItem || defaultSearchInItem;
      const currentIndex =
        direction === "forward"
          ? visibleRange.endIndex
          : visibleRange.startIndex;
      const searchStart =
        direction === "forward"
          ? Math.max(0, currentIndex + 1)
          : Math.min(data.length - 1, currentIndex - 1);
      const step = direction === "forward" ? 1 : -1;

      for (let i = searchStart; i >= 0 && i < data.length; i += step) {
        if (searchFn(data[i], term)) {
          // Found a match! Set up callback and scroll to it
          pendingSearchCallback.current = onContentReady;

          listHandle.current?.scrollToIndex({
            index: i,
            behavior: "auto",
            align: "center",
          });

          return true;
        }
      }

      return false;
    },
    [data, searchInItem, defaultSearchInItem, visibleRange],
  );

  // Register with search context
  useEffect(() => {
    const unregister = registerVirtualList(id, searchInData);
    return unregister;
  }, [id, registerVirtualList, searchInData]);

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
  const hasScrolled = useRef(false);
  useEffect(() => {
    if (initialTopMostItemIndex !== undefined && listHandle.current) {
      // If there is an initial index, scroll to it after a short delay
      const timer = setTimeout(() => {
        listHandle.current?.scrollToIndex({
          index: initialTopMostItemIndex,
          align: "start",
          behavior: !hasScrolled.current ? "auto" : "smooth",
          offset: offsetTop ? -offsetTop : undefined,
        });
        hasScrolled.current = true;
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [initialTopMostItemIndex]);

  // Watch for scrolling to stop and trigger pending search callback
  useEffect(() => {
    if (!isCurrentlyScrolling && pendingSearchCallback.current) {
      // Add a delay to ensure DOM is fully updated after scrolling stops
      setTimeout(() => {
        const callback = pendingSearchCallback.current;
        pendingSearchCallback.current = null;
        callback?.();
      }, 100);
    }
  }, [isCurrentlyScrolling]);

  // Custom scrolling state callback
  const handleScrollingChange = useCallback(
    (scrolling: boolean) => {
      setIsCurrentlyScrolling(scrolling);
      // Also call the original isScrolling callback from useVirtuosoState
      isScrolling(scrolling);
    },
    [isScrolling],
  );

  return (
    <Virtuoso
      ref={listHandle}
      customScrollParent={scrollRef?.current ? scrollRef.current : undefined}
      style={{ height: "100%", width: "100%" }}
      data={data}
      defaultItemHeight={500}
      itemContent={renderRow}
      increaseViewportBy={{ top: 1000, bottom: 1000 }}
      overscan={{ main: 5, reverse: 5 }}
      className={clsx("transcript", className)}
      isScrolling={handleScrollingChange}
      rangeChanged={(range) => {
        setVisibleRange(range);
      }}
      restoreStateFrom={getRestoreState()}
      totalListHeightChanged={heightChanged}
      components={{
        Footer,
        ...components,
      }}
    />
  );
};
