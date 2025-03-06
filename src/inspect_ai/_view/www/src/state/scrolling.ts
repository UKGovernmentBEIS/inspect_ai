import { RefObject, useCallback, useEffect } from "react";
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
  delay = 500,
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
      // Ensure the element has fully rendered
      requestAnimationFrame(() => {
        if (element.scrollTop !== savedPosition) {
          element.scrollTop = savedPosition;
        }
      });
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

export const useVirtuosoState = (
  virtuosoRef: RefObject<VirtuosoHandle | null>,
  elementKey: string,
  delay = 500,
) => {
  const getListPosition = useStore((state) => state.appActions.getListPosition);
  const setListPosition = useStore((state) => state.appActions.setListPosition);

  // Create debounced scroll handler
  const handleStateChange: StateCallback = useCallback(
    (state: StateSnapshot) => {
      log.debug(`Storing list state: [${elementKey}]`, state);
      setListPosition(elementKey, state);
    },
    [elementKey, setListPosition, delay],
  );

  const restoreState = useCallback(() => {
    return getListPosition(elementKey);
  }, [getListPosition]);

  const isScrolling = useCallback(
    debounce((isScrolling: boolean) => {
      log.debug("List scroll", isScrolling);
      const element = virtuosoRef.current;
      if (!element) {
        return;
      }
      element.getState(handleStateChange);
    }, delay),
    [setListPosition, handleStateChange],
  );
  return { restoreState, isScrolling };
};
