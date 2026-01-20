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

  // Optional function to extract searchable text from data items
  // If not provided, will use JSON.stringify as fallback
  // Return a string or array of strings to search within
  itemSearchText?: (item: T) => string | string[];
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
  itemSearchText,
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
  }, [followOutput, live, setFollowOutput]);

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
  }, [live, followOutput, prevLive, scrollRef, setFollowOutput]);

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
    [followOutput, live, scrollRef, listHandle],
  );

  const forceUpdate = useCallback(() => forceRender({}), []);

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
  }, [forceUpdate]);

  const [, forceRender] = useState({});

  // Default function to extract searchable text using JSON.stringify
  const defaultItemSearchText = useCallback((item: T): string => {
    try {
      return JSON.stringify(item);
    } catch {
      return "";
    }
  }, []);

  // Search within a single text string
  const searchInText = useCallback(
    (text: string, searchTerm: string): boolean => {
      const lowerText = text.toLowerCase();
      const prepared = prepareSearchTerm(searchTerm);

      // Simple search
      if (lowerText.includes(prepared.simple)) {
        return true;
      }

      // Check variations
      if (prepared.unquoted && lowerText.includes(prepared.unquoted)) {
        return true;
      }

      if (prepared.jsonEscaped && lowerText.includes(prepared.jsonEscaped)) {
        return true;
      }

      return false;
    },
    [],
  );

  // Search within an item using itemSearchText
  const searchInItem = useCallback(
    (item: T, searchTerm: string): boolean => {
      const getSearchText = itemSearchText ?? defaultItemSearchText;
      const texts = getSearchText(item);
      const textArray = Array.isArray(texts) ? texts : [texts];

      return textArray.some((text) => searchInText(text, searchTerm));
    },
    [itemSearchText, defaultItemSearchText, searchInText],
  );

  // Search in data function
  const searchInData: ExtendedFindFn = useCallback(
    async (
      term: string,
      direction: "forward" | "backward",
      onContentReady: () => void,
    ) => {
      if (!data.length || !term) return false;

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
        if (searchInItem(data[i], term)) {
          // Found a match! Set up callback and scroll to it
          pendingSearchCallback.current = onContentReady;

          listHandle.current?.scrollToIndex({
            index: i,
            behavior: "auto",
            align: "center",
          });

          // Fallback timeout if Virtuoso doesn't trigger scroll callbacks
          setTimeout(() => {
            if (pendingSearchCallback.current === onContentReady) {
              pendingSearchCallback.current = null;
              onContentReady();
            }
          }, 200);

          return true;
        }
      }

      return false;
    },
    [
      data,
      searchInItem,
      visibleRange.endIndex,
      visibleRange.startIndex,
      listHandle,
    ],
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
  }, [initialTopMostItemIndex, listHandle, offsetTop]);

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

type PreparedSearchTerms = {
  simple: string;
  unquoted?: string;
  jsonEscaped?: string;
};

const prepareSearchTerm = (term: string): PreparedSearchTerms => {
  const lower = term.toLowerCase();

  // No special characters that need JSON handling
  if (!term.includes('"') && !term.includes(":")) {
    return { simple: lower };
  }

  // Generate variations for JSON-like syntax
  return {
    simple: lower,
    // Remove quotes
    unquoted: lower.replace(/"/g, ""),
    // Escape quotes for JSON
    jsonEscaped: lower.replace(/"/g, '\\"'),
  };
};
