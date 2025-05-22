import { RefObject, useCallback, useEffect, useRef } from "react";
import { StateCallback, StateSnapshot, VirtuosoHandle } from "react-virtuoso";
import { createLogger } from "../utils/logger";
import { debounce, throttle } from "../utils/sync";
import { useStore } from "./store";

const log = createLogger("scrolling");

export function useStatefulScrollPosition<
  T extends HTMLElement = HTMLDivElement,
>(
  elementRef: RefObject<T | null>,
  elementKey: string,
  delay = 1000,
  scrollable = true,
) {
  const getScrollPosition = useStore(
    (state) => state.appActions.getScrollPosition,
  );
  const setScrollPosition = useStore(
    (state) => state.appActions.setScrollPosition,
  );

  // Create debounced scroll handler
  const handleScroll = useCallback(
    debounce((e: Event) => {
      const target = e.target as HTMLElement;
      const position = target.scrollTop;
      log.debug(`Storing scroll position`, elementKey, position);
      setScrollPosition(elementKey, position);
    }, delay),
    [elementKey, setScrollPosition, delay],
  );

  // Function to manually restore scroll position
  const restoreScrollPosition = useCallback(() => {
    const element = elementRef.current;
    const savedPosition = getScrollPosition(elementKey);

    if (element && savedPosition !== undefined) {
      requestAnimationFrame(() => {
        element.scrollTop = savedPosition;

        requestAnimationFrame(() => {
          if (element.scrollTop !== savedPosition) {
            element.scrollTop = savedPosition;
          }
        });
      });
    }
  }, [elementKey, getScrollPosition, elementRef]);

  // Set up scroll listener and restore position on mount
  useEffect(() => {
    const element = elementRef.current;
    if (!element || !scrollable) {
      return;
    }
    log.debug(`Restore Scroll Hook`, elementKey);

    // Restore scroll position on mount
    const savedPosition = getScrollPosition(elementKey);
    if (savedPosition !== undefined) {
      log.debug(`Restoring scroll position`, savedPosition);

      // Function to check and restore scroll position
      const tryRestoreScroll = () => {
        // Check if element has content to scroll (scrollHeight > clientHeight)
        if (element.scrollHeight > element.clientHeight) {
          if (element.scrollTop !== savedPosition) {
            element.scrollTop = savedPosition;
            log.debug(`Scroll position restored to ${savedPosition}`);
          }
          return true; // Successfully restored
        }
        return false; // Not ready yet
      };

      // Try immediately once
      if (!tryRestoreScroll()) {
        // If not successful, set up polling with setTimeout for 1-second intervals
        let attempts = 0;
        const maxAttempts = 5; // Fewer attempts since we're waiting longer

        const pollForRender = () => {
          if (tryRestoreScroll() || attempts >= maxAttempts) {
            // Either success or max attempts reached
            if (attempts >= maxAttempts) {
              log.debug(
                `Failed to restore scroll after ${maxAttempts} attempts`,
              );
            }
            return;
          }

          attempts++;
          // Wait 1 second before trying again
          setTimeout(pollForRender, 1000);
        };

        // Start polling after 1 second
        setTimeout(pollForRender, 1000);
      }
    }

    // Set up scroll listener
    if (element.addEventListener) {
      element.addEventListener("scroll", handleScroll);
    } else {
      log.warn("Element has no way to add event listener", element);
    }

    // Clean up
    return () => {
      if (element.removeEventListener) {
        element.removeEventListener("scroll", handleScroll);
      } else {
        log.warn("Element has no way to remove event listener", element);
      }
    };
  }, [elementKey, elementRef, handleScroll]);

  return { restoreScrollPosition };
}

// Define a type for the debounced function that includes the cancel method
type DebouncedFunction<T extends (...args: any[]) => any> = T & {
  cancel: () => void;
  flush: () => void;
};

export const useVirtuosoState = (
  virtuosoRef: RefObject<VirtuosoHandle | null>,
  elementKey: string,
  delay = 1000,
) => {
  // Use useCallback to stabilize the selectors
  const restoreState = useStore(
    useCallback((state) => state.app.listPositions[elementKey], [elementKey]),
  );

  const setListPosition = useStore(
    useCallback((state) => state.appActions.setListPosition, []),
  );

  const clearListPosition = useStore(
    useCallback((state) => state.appActions.clearListPosition, []),
  );

  // Properly type the debounced function ref
  const debouncedFnRef = useRef<DebouncedFunction<
    (isScrolling: boolean) => void
  > | null>(null);

  // Create the state change handler
  const handleStateChange: StateCallback = useCallback(
    (state: StateSnapshot) => {
      log.debug(`Storing list state: [${elementKey}]`, state);
      setListPosition(elementKey, state);
    },
    [elementKey, setListPosition],
  );

  // Setup the debounced function once
  useEffect(() => {
    debouncedFnRef.current = debounce((isScrolling: boolean) => {
      log.debug("List scroll", isScrolling);
      const element = virtuosoRef.current;
      if (!element) {
        return;
      }
      element.getState(handleStateChange);
    }, delay) as DebouncedFunction<(isScrolling: boolean) => void>;

    return () => {
      // Clear the stored position when component unmounts
      clearListPosition(elementKey);
    };
  }, [delay, elementKey, handleStateChange, clearListPosition, virtuosoRef]);

  // Return a stable function reference that uses the ref internally
  const isScrolling = useCallback((scrolling: boolean) => {
    if (!scrolling) {
      return;
    }

    if (debouncedFnRef.current) {
      debouncedFnRef.current(scrolling);
    }
  }, []);

  // Use a state to prevent re-rendering just because the restore
  // state changes
  const stateRef = useRef(restoreState);
  useEffect(() => {
    stateRef.current = restoreState;
  }, [restoreState]);

  const getRestoreState = useCallback(() => stateRef.current, []);

  return { getRestoreState, isScrolling };
};

export function useRafThrottle<T extends (...args: any[]) => any>(
  callback: T,
  dependencies: any[] = [],
): (...args: Parameters<T>) => void {
  const rafRef = useRef<number | null>(null);
  const callbackRef = useRef<T>(callback);

  // Update the callback ref when the callback changes
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback, ...dependencies]);

  const throttledCallback = useCallback((...args: Parameters<T>) => {
    // Skip if we already have a frame queued
    if (rafRef.current) {
      return;
    }

    rafRef.current = requestAnimationFrame(() => {
      callbackRef.current(...args);
      rafRef.current = null;
    });
  }, []);

  // Clean up any pending animation frame on unmount
  useEffect(() => {
    return () => {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, []);

  return throttledCallback;
}

interface ScrollCacheEntry {
  position: number;
  stale: boolean;
}

export interface ScrollTrackingOptions {
  topOffset?: number;
  bottomOffset?: number;
}

/**
 * A hook that tracks scroll position and determines which element from a list
 * should be considered "active" based on the current scroll position.
 *
 * @param elementIds - Array of element IDs to track
 * @param onElementVisible - Callback function triggered when an element becomes the active one
 * @param scrollRef - Optional ref to a scrollable container. If not provided, window scroll is used
 */
export function useScrollTracking(
  elementIds: string[],
  onElementVisible: (id: string) => void,
  scrollRef?: RefObject<HTMLElement | null>,
  options?: ScrollTrackingOptions,
): void {
  // Cache of element positions to avoid recalculating on every scroll
  const positionCache = useRef<Record<string, ScrollCacheEntry>>({});

  // Track when element IDs change to update the cache
  const idsRef = useRef<string[]>(elementIds);

  // Track which item was last 'selected'
  const selectedIdRef = useRef<string | null>(null);

  // Track if we're in the middle of a smooth scroll
  const isScrollingRef = useRef<boolean>(false);

  const getAbsScrollTop = useCallback(() => {
    const scrollTop = scrollRef?.current
      ? scrollRef.current.scrollTop
      : (window.scrollY || document.documentElement.scrollTop) -
        document.documentElement.getBoundingClientRect().top;
    return scrollTop;
  }, [scrollRef]);

  // Compute absolute positions for elements regardless of scroll state
  const updateCache = useCallback(() => {
    if (elementIds.length === 0) return;

    // Get all elements in the list and calculate their absolute positions
    for (const elementId of elementIds) {
      if (
        !positionCache.current[elementId] ||
        positionCache.current[elementId].stale
      ) {
        const el = document.getElementById(elementId);
        if (el) {
          // Calculate the absolute position by getting the element's offset from the top of its offset parent,
          // then adding all parent offsets until we reach the top of the document/container
          let absolutePosition = 0;

          // If we're using a custom scroll container, measure position relative to that container
          if (scrollRef?.current) {
            // Get offset position relative to the scroll container
            const scrollContainer = scrollRef.current;
            const containerRect = scrollContainer.getBoundingClientRect();
            const elementRect = el.getBoundingClientRect();

            // Position relative to container is element's top minus container's top
            absolutePosition = elementRect.top - containerRect.top;
          } else {
            // For window scrolling, calculate actual document position
            // This gives us an absolute position that doesn't change with scrolling
            let currentEl: HTMLElement | null = el;

            while (currentEl && currentEl !== document.body) {
              absolutePosition += currentEl.offsetTop;
              currentEl = currentEl.offsetParent as HTMLElement;
            }
          }

          log.debug(`Absolute position for ${elementId}:`, absolutePosition);

          positionCache.current[elementId] = {
            position: absolutePosition,
            stale: false,
          };
        }
      }
    }
  }, [elementIds, scrollRef]);

  const findLargestElLessThanOrEqual = (position: number): string | null => {
    let bestKey: string | null = null;
    let bestValue: number = -Infinity;

    for (const [key, value] of Object.entries(positionCache.current)) {
      // Find the largest element position that is less than or equal to scroll position
      if (value.position <= position && value.position > bestValue) {
        bestKey = key;
        bestValue = value.position;
      }
    }

    return bestKey;
  };

  // Using the absolute positions and current scroll position, find the selected element
  const selectedElementId = useCallback(() => {
    // If we have no elements, return null
    if (elementIds.length === 0) {
      return null;
    }

    // Ensure all positions are calculated
    const hasAllPositions = elementIds.every(
      (id) => positionCache.current[id] && !positionCache.current[id].stale,
    );

    if (!hasAllPositions) {
      updateCache();
    }

    // Get current scroll position with offset
    const topOffset = options?.topOffset || 60; // Default 60px offset
    const currentScrollPosition = getAbsScrollTop() + topOffset;

    // Check if we're at the bottom of the scroll area
    if (
      scrollRef?.current &&
      scrollRef.current.scrollHeight - scrollRef.current.scrollTop <=
        scrollRef.current.clientHeight + (options?.bottomOffset || 10)
    ) {
      log.debug("At bottom of scroll area, selecting last element");
      return elementIds[elementIds.length - 1];
    }

    // Compare the scroll position against each element's absolute position
    // When using the scroll container, we don't need to add scrollTop since our positions
    // are already relative to the container
    const position = currentScrollPosition;

    log.debug("Current scroll position for selection:", position);

    // Find the element with largest position <= scroll position
    const el = findLargestElLessThanOrEqual(position);

    // If no element was found, select the first element as fallback
    if (el === null && elementIds.length > 0) {
      return elementIds[0];
    }

    return el;
  }, [elementIds, scrollRef, getAbsScrollTop, updateCache, options]);

  // set stale flag on positions to try to get them to recompute when the
  // size changes

  // Update refs and cache when elementIds change
  useEffect(() => {
    const oldIds = new Set(idsRef.current);
    const newIds = new Set(elementIds);

    // Clear cache entries for IDs that are no longer in the list
    if (idsRef.current !== elementIds) {
      Object.keys(positionCache.current).forEach((id) => {
        if (!newIds.has(id)) {
          delete positionCache.current[id];
        }
      });

      // Check for new IDs that weren't in the previous list
      const hasNewIds = elementIds.some((id) => !oldIds.has(id));

      // If we have new IDs, we should update positions
      if (hasNewIds) {
        updateCache();
      }
      idsRef.current = elementIds;
    }
  }, [elementIds, updateCache]);

  // Use RAF throttling to optimize scroll handling
  const handleScrollEnd = useCallback(
    throttle(() => {
      isScrollingRef.current = false;

      // First, update the cache
      updateCache();

      // Get the currently selected element ID
      const selectedId = selectedElementId();

      if (selectedId !== null && selectedId !== selectedIdRef.current) {
        // If the selected ID is different from the last one, call the callback
        if (onElementVisible) {
          onElementVisible(selectedId);
        }
        selectedIdRef.current = selectedId;
      }
    }, 100),
    [updateCache, selectedElementId, onElementVisible],
  );

  const handleScroll = useRafThrottle(() => {
    if (elementIds.length === 0) return;

    // Mark that we're currently scrolling
    isScrollingRef.current = true;

    // Invoke the debounced function
    handleScrollEnd();
  }, [elementIds, handleScrollEnd]);

  // Set up scroll listener and initialize cache
  useEffect(() => {
    if (elementIds.length === 0) return;

    const scrollElement = scrollRef?.current || window;

    // Initial position update
    updateCache();

    // Initial check to set the active element
    handleScroll();

    // Add scroll event listener
    scrollElement.addEventListener("scroll", handleScroll);

    // Add resize listener to update positions when window size changes
    window.addEventListener("resize", updateCache);

    // Cleanup
    return () => {
      scrollElement.removeEventListener("scroll", handleScroll);
      window.removeEventListener("resize", updateCache);
    };
  }, [elementIds, handleScroll, scrollRef, updateCache]);
}
