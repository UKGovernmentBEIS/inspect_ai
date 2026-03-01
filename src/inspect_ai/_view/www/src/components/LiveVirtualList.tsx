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
import {
  ExtendedCountFn,
  GoToMatchFn,
  useExtendedFind,
} from "./ExtendedFindContext";
import { PulsingDots } from "./PulsingDots";
import {
  buildSearchableText,
  countMatches,
  createMatchRange,
  findNthMatch,
  getAllMatchRangesInPanel,
} from "./searchUtils";
import { scrollRangeToCenter } from "../utils/dom";

import styles from "./LiveVirtualList.module.css";

function highlightNthOccurrenceInPanel(
  panelId: string,
  term: string,
  occurrence: number,
): boolean {
  const panelEl = document.getElementById(panelId);
  if (!panelEl) return false;

  const { text, nodes, offsets } = buildSearchableText(panelEl);
  const match = findNthMatch(text, term, occurrence);
  if (!match) return false;

  const result = createMatchRange(nodes, offsets, match);
  if (!result) return false;

  const { range, staticRange } = result;

  // CSS Custom Highlight — visible regardless of input focus
  if (typeof Highlight !== "undefined" && CSS?.highlights) {
    CSS.highlights.set("find-match-current", new Highlight(staticRange));
  }

  const sel = window.getSelection();
  if (sel) {
    sel.removeAllRanges();
    sel.addRange(range);
  }

  return true;
}

// Count the number of searchable DOM occurrences of `term` in a rendered panel.
function countMatchesInPanel(panelId: string, term: string): number {
  const panelEl = document.getElementById(panelId);
  if (!panelEl) return 0;
  const { text } = buildSearchableText(panelEl);
  return countMatches(text, term);
}

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

  const {
    registerMatchCounter,
    registerGoToMatch,
  } = useExtendedFind();
  const pendingTargetRef = useRef<{
    index: number;
    resolve: () => void;
  } | null>(null);
  const visibleRangeRef = useRef(visibleRange);
  const currentHighlightRef = useRef<{
    panelId: string;
    term: string;
    occurrence: number;
  } | null>(null);
  const navTokenRef = useRef(0);
  const activeSearchTermRef = useRef<string>("");

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

  useEffect(() => {
    visibleRangeRef.current = visibleRange;
  }, [visibleRange]);

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

  const scrollToMatch = useCallback(
    (index: number): Promise<void> => {
      return new Promise((resolve) => {
        const currentRange = visibleRangeRef.current;
        if (index >= currentRange.startIndex && index <= currentRange.endIndex) {
          requestAnimationFrame(() => resolve());
          return;
        }

        pendingTargetRef.current = { index, resolve };
        listHandle.current?.scrollToIndex({
          index,
          behavior: "auto",
          align: "center",
        });

        setTimeout(() => {
          if (pendingTargetRef.current?.index === index) {
            pendingTargetRef.current = null;
            resolve();
          }
        }, 2000);
      });
    },
    [listHandle],
  );

  const countMatchesInData: ExtendedCountFn = useCallback(
    (term: string): number => {
      if (!term || !data.length) return 0;
      const lower = term.toLowerCase();
      let total = 0;
      const getSearchText = itemSearchText ?? defaultItemSearchText;

      for (const item of data) {
        const texts = getSearchText(item);
        const textArray = Array.isArray(texts) ? texts : [texts];
        for (const text of textArray) {
          const lowerText = text.toLowerCase();
          let pos = 0;
          let nextPos = lowerText.indexOf(lower, pos);
          while (nextPos !== -1) {
            pos = nextPos;
            total++;
            pos += lower.length;
            nextPos = lowerText.indexOf(lower, pos);
          }
        }
      }
      return total;
    },
    [data, itemSearchText, defaultItemSearchText],
  );

  const rebuildVisibleHighlights = useCallback(
    (term: string, currentOccurrence?: number, currentPanelId?: string) => {
      if (!term || typeof Highlight === "undefined" || !CSS?.highlights) return;
      const allRanges: StaticRange[] = [];
      const range = visibleRangeRef.current;
      for (let i = range.startIndex; i <= range.endIndex && i < data.length; i++) {
        const nodeId = (data[i] as { id?: string }).id;
        if (!nodeId) continue;
        const panelId = "event-panel-" + nodeId;
        const excludeOcc =
          panelId === currentPanelId ? currentOccurrence : undefined;
        allRanges.push(...getAllMatchRangesInPanel(panelId, term, excludeOcc));
        if (allRanges.length > 500) break;
      }
      if (allRanges.length > 0) {
        CSS.highlights.set("find-match-all", new Highlight(...allRanges));
      } else {
        CSS.highlights.delete("find-match-all");
      }
    },
    [data],
  );


  // Navigate to the nth match (1-based). Uses data-level counts to locate
  // the target item WITHOUT scrolling, then scrolls to ONLY that item and
  // highlights using DOM-level TreeWalker. If the DOM has fewer matches
  // than the data (common for JSON fields rendered as expandable views),
  // we continue to the next matching item.
  const goToMatchImpl: GoToMatchFn = useCallback(
    async (term: string, absoluteIndex: number): Promise<boolean> => {
      if (!data.length || !term || absoluteIndex < 1) return false;

      const thisNav = ++navTokenRef.current;
      activeSearchTermRef.current = term;

      const getSearchText = itemSearchText ?? defaultItemSearchText;
      const lower = term.toLowerCase();

      // Phase 1: Walk all data items to find which item the target falls in.
      //          NO scrolling — just data-level counting.
      let cumulative = 0;
      let targetIdx = -1;
      let occurrenceInItem = 0;

      for (let i = 0; i < data.length; i++) {
        if (!searchInItem(data[i], term)) continue;

        const texts = getSearchText(data[i]);
        const textArray = Array.isArray(texts) ? texts : [texts];
        let matchesInItem = 0;
        for (const text of textArray) {
          const lt = text.toLowerCase();
          let pos = 0;
          let nextPos = lt.indexOf(lower, pos);
          while (nextPos !== -1) {
            pos = nextPos;
            matchesInItem++;
            pos += lower.length;
            nextPos = lt.indexOf(lower, pos);
          }
        }

        if (cumulative + matchesInItem >= absoluteIndex) {
          targetIdx = i;
          occurrenceInItem = absoluteIndex - cumulative;
          break;
        }
        cumulative += matchesInItem;
      }

      if (targetIdx === -1) return false;

      // Phase 2: Scroll to the target item (and possibly subsequent items
      //          if DOM has fewer matches than data predicted).
      for (let i = targetIdx; i < data.length; i++) {
        if (i !== targetIdx && !searchInItem(data[i], term)) continue;

        const nodeId = (data[i] as { id?: string }).id;
        if (!nodeId) continue;
        const panelId = "event-panel-" + nodeId;

        await scrollToMatch(i);

        if (navTokenRef.current !== thisNav) return false;

        const domMatches = countMatchesInPanel(panelId, term);

        if (occurrenceInItem <= domMatches) {
          if (highlightNthOccurrenceInPanel(panelId, term, occurrenceInItem)) {
            if (navTokenRef.current !== thisNav) return false;

            const sel = window.getSelection();
            if (sel && sel.rangeCount > 0) {
              scrollRangeToCenter(sel.getRangeAt(0));
              sel.removeAllRanges();
            }

            currentHighlightRef.current = {
              panelId,
              term,
              occurrence: occurrenceInItem,
            };

            rebuildVisibleHighlights(term, occurrenceInItem, panelId);

            return true;
          }
        }

        // DOM has fewer matches than data predicted — skip ahead.
        occurrenceInItem -= domMatches;
      }

      return false;
    },
    [
      data,
      itemSearchText,
      defaultItemSearchText,
      searchInItem,
      scrollToMatch,
      rebuildVisibleHighlights,
    ],
  );

  useEffect(() => {
    const unregisterCount = registerMatchCounter(id, countMatchesInData);
    const unregisterGoTo = registerGoToMatch(id, goToMatchImpl);
    return () => {
      unregisterCount();
      unregisterGoTo();
    };
  }, [
    id,
    registerMatchCounter,
    registerGoToMatch,
    countMatchesInData,
    goToMatchImpl,
  ]);

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
      isScrolling={isScrolling}
      rangeChanged={(range) => {
        setVisibleRange(range);
        visibleRangeRef.current = range;

        const pending = pendingTargetRef.current;
        if (
          pending &&
          pending.index >= range.startIndex &&
          pending.index <= range.endIndex
        ) {
          pendingTargetRef.current = null;
          requestAnimationFrame(() => pending.resolve());
        }

        const term = activeSearchTermRef.current;
        const highlight = currentHighlightRef.current;
        if (term) {
          requestAnimationFrame(() => {
            if (highlight) {
              const panelEl = document.getElementById(highlight.panelId);
              if (panelEl && panelEl.isConnected) {
                highlightNthOccurrenceInPanel(
                  highlight.panelId,
                  highlight.term,
                  highlight.occurrence,
                );
                window.getSelection()?.removeAllRanges();
              }
            }
            rebuildVisibleHighlights(term, highlight?.occurrence, highlight?.panelId);
          });
        }
      }}
      skipAnimationFrameInResizeObserver={true}
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
