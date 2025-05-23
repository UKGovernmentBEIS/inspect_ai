import { RefObject, useCallback, useEffect, useRef } from "react";
import { StateCallback, StateSnapshot, VirtuosoHandle } from "react-virtuoso";
import { createLogger } from "../utils/logger";
import { debounce } from "../utils/sync";
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

export function useScrollTrack(
  elementIds: string[],
  onElementVisible: (id: string) => void,
  scrollRef?: RefObject<HTMLElement | null>,
  options?: { topOffset?: number; checkInterval?: number },
) {
  const currentVisibleRef = useRef<string | null>(null);
  const lastCheckRef = useRef<number>(0);
  const rafRef = useRef<number | null>(null);

  const findTopmostVisibleElement = useCallback(() => {
    const container = scrollRef?.current;
    const containerRect = container?.getBoundingClientRect();
    const topOffset = options?.topOffset ?? 50;

    // Define viewport bounds
    const viewportTop = containerRect
      ? containerRect.top + topOffset
      : topOffset;
    const viewportBottom = containerRect
      ? containerRect.bottom
      : window.innerHeight;
    const viewportHeight = viewportBottom - viewportTop;

    // Calculate dynamic threshold based on scroll position
    let detectionPoint = viewportTop;

    if (container) {
      // This will track the scroll position and select which element is 'showing'
      // This is generally the item at the the top of the viewport (threshold).
      // As we get to the bottom of the scroll area, though, we will actually start
      // sliding the detection point down to the bottom of the viewport so that every
      // item can be selected.
      const scrollHeight = container.scrollHeight;
      const scrollTop = container.scrollTop;
      const clientHeight = container.clientHeight;
      const maxScroll = scrollHeight - clientHeight;

      // Calculate how close we are to the bottom (0 = at top, 1 = at bottom)
      const scrollProgress = maxScroll > 0 ? scrollTop / maxScroll : 0;

      // Start sliding only in the last 20% of scroll
      const slideThreshold = 0.8;
      if (scrollProgress > slideThreshold) {
        // Calculate how far through the slide zone we are (0 to 1)
        const slideProgress =
          (scrollProgress - slideThreshold) / (1 - slideThreshold);
        // Use a steeper curve (power of 3) for faster transition
        const easedProgress = Math.pow(slideProgress, 3);
        // Slide all the way from top to bottom of viewport
        detectionPoint = viewportTop + viewportHeight * 0.9 * easedProgress;
      }

      // When fully scrolled to bottom, use bottom of viewport
      if (scrollProgress >= 0.99) {
        detectionPoint = viewportBottom - 50; // Slight offset from absolute bottom
      }
    }

    let closestId: string | null = null;
    let closestDistance = Infinity;

    // Create a Set for O(1) lookup
    const elementIdSet = new Set(elementIds);

    // Find all elements that are actually in the DOM and check if they're our tracked elements
    const elements = container
      ? container.querySelectorAll("[id]")
      : document.querySelectorAll("[id]");

    for (const element of elements) {
      const id = element.id;

      // Check if this element is one we're tracking
      if (elementIdSet.has(id)) {
        const rect = element.getBoundingClientRect();

        // Check if element is in viewport
        if (rect.bottom >= viewportTop && rect.top <= viewportBottom) {
          // Calculate distance from detection point to element's vertical center
          const elementCenter = rect.top + rect.height / 2;
          const distance = Math.abs(elementCenter - detectionPoint);

          if (distance < closestDistance) {
            closestDistance = distance;
            closestId = id;
          }
        }
      }
    }

    return closestId;
  }, [elementIds, scrollRef, options?.topOffset]);

  const checkVisibility = useCallback(() => {
    const now = Date.now();
    const checkInterval = options?.checkInterval ?? 100;

    // Throttle checks
    if (now - lastCheckRef.current < checkInterval) {
      return;
    }

    lastCheckRef.current = now;
    const topmostId = findTopmostVisibleElement();

    if (topmostId !== currentVisibleRef.current) {
      currentVisibleRef.current = topmostId;
      if (topmostId) {
        onElementVisible(topmostId);
      }
    }
  }, [findTopmostVisibleElement, onElementVisible, options?.checkInterval]);

  const handleScroll = useCallback(() => {
    // Cancel any pending animation frame
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
    }

    // Schedule visibility check on next animation frame
    rafRef.current = requestAnimationFrame(() => {
      checkVisibility();
      rafRef.current = null;
    });
  }, [checkVisibility]);

  useEffect(() => {
    if (elementIds.length === 0) return;

    const scrollElement = scrollRef?.current || window;

    // Initial check
    checkVisibility();

    // Add scroll listener
    scrollElement.addEventListener("scroll", handleScroll, { passive: true });

    // Also check periodically for virtual elements that may have appeared
    const intervalId = setInterval(checkVisibility, 1000);

    // Cleanup
    return () => {
      scrollElement.removeEventListener("scroll", handleScroll);
      clearInterval(intervalId);
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
      }
    };
  }, [elementIds, scrollRef, handleScroll, checkVisibility]);
}
