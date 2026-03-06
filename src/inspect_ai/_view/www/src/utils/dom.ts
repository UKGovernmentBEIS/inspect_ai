import { useEffect, useRef } from "react";

/**
 * Finds the nearest scrollable ancestor of an element.
 * Useful for programmatic scrolling when you need to find the scroll container.
 *
 * @param element - The element to start searching from
 * @param options.minScrollBuffer - Minimum difference between scrollHeight and clientHeight
 *                                  to consider an element scrollable (default: 100)
 * @returns The scrollable parent element, or null if none found
 */
export function findScrollableParent(
  element: Element | null,
  options?: { minScrollBuffer?: number },
): HTMLElement | null {
  const minBuffer = options?.minScrollBuffer ?? 100;
  let current =
    element instanceof HTMLElement ? element : element?.parentElement;

  while (current && current !== document.body) {
    const style = getComputedStyle(current);
    if (
      (style.overflowY === "auto" || style.overflowY === "scroll") &&
      current.scrollHeight > current.clientHeight + minBuffer
    ) {
      return current;
    }
    current = current.parentElement;
  }
  return null;
}

/**
 * Scrolls a Range (text selection) to the center of its scrollable container.
 * Unlike element.scrollIntoView({ block: "center" }), this works correctly
 * for selections within large elements (e.g., code blocks) by scrolling to
 * the actual selection position rather than the element's top.
 *
 * @param range - The Range to scroll into view
 * @param options.behavior - Scroll behavior ('auto' or 'smooth'), default: 'auto'
 * @param options.fallbackToScrollIntoView - Whether to fall back to scrollIntoView
 *                                           if no scrollable parent is found (default: true)
 */
export function scrollRangeToCenter(
  range: Range,
  options?: { behavior?: ScrollBehavior; fallbackToScrollIntoView?: boolean },
): void {
  const { behavior = "auto", fallbackToScrollIntoView = true } = options ?? {};

  const rects = range.getClientRects();
  if (rects.length === 0) return;

  const selectionRect = rects[0];
  const scrollableParent = findScrollableParent(
    range.startContainer.parentElement,
  );

  if (scrollableParent) {
    const parentRect = scrollableParent.getBoundingClientRect();
    const selectionOffsetInParent =
      selectionRect.top - parentRect.top + scrollableParent.scrollTop;
    const targetScrollTop =
      selectionOffsetInParent - scrollableParent.clientHeight / 2;

    scrollableParent.scrollTo({
      top: Math.max(0, targetScrollTop),
      behavior,
    });
  } else if (fallbackToScrollIntoView) {
    range.startContainer.parentElement?.scrollIntoView({
      behavior,
      block: "center",
    });
  }
}

// Custom hook to observe size changes
export const useResizeObserver = (
  callback: (entry: ResizeObserverEntry) => void,
) => {
  const elementRef = useRef<HTMLDivElement>(null);
  const observerRef = useRef<ResizeObserver | null>(null);

  useEffect(() => {
    const element = elementRef.current;
    if (!element) return;

    observerRef.current = new ResizeObserver((entries) => {
      if (entries[0]) {
        callback(entries[0]);
      }
    });

    observerRef.current.observe(element);

    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect();
      }
    };
  }, [callback]);

  return elementRef;
};
