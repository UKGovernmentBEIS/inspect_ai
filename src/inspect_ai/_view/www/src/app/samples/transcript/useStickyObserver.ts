import { useEffect, useRef, useState } from "react";
import { useStickyScrollContainer } from "../../../components/StickyScrollContext";

// Sticky observer using scroll events
// workaround for https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@container#stuck
// use as :global([data-useStickyObserver-stuck]) in CSS modules

// Track scroll listeners per container to avoid duplicate listeners
const scrollListenerMap = new Map<
  Element | null,
  { elements: Set<Element>; cleanup: () => void }
>();

function updateStickyState(container: Element | null, elements: Set<Element>) {
  const containerRect = container?.getBoundingClientRect();
  const containerTop = containerRect?.top ?? 0;
  const stickyTop =
    parseFloat(
      getComputedStyle(document.body).getPropertyValue(
        "--inspect-event-panel-sticky-top",
      ),
    ) || 0;

  elements.forEach((el) => {
    const rect = el.getBoundingClientRect();
    // Element is stuck when its top is at or near the sticky position relative to container
    // We check if the element's top (relative to container) is at the sticky position
    const relativeTop = rect.top - containerTop;
    const isStuck =
      relativeTop <= stickyTop + 1 && relativeTop >= stickyTop - 1;

    el.toggleAttribute("data-useStickyObserver-stuck", isStuck);
  });
}

function getScrollListener(container: Element | null) {
  let entry = scrollListenerMap.get(container);
  if (!entry) {
    const elements = new Set<Element>();
    let rafId: number | null = null;

    const handleScroll = () => {
      // Use requestAnimationFrame to throttle updates to once per frame
      if (rafId === null) {
        rafId = requestAnimationFrame(() => {
          updateStickyState(container, elements);
          rafId = null;
        });
      }
    };

    // Use the container for scroll events, or window if no container
    const scrollTarget = container || window;
    scrollTarget.addEventListener("scroll", handleScroll, { passive: true });

    // Also update on resize
    window.addEventListener("resize", handleScroll, { passive: true });

    const cleanup = () => {
      scrollTarget.removeEventListener("scroll", handleScroll);
      window.removeEventListener("resize", handleScroll);
      if (rafId !== null) {
        cancelAnimationFrame(rafId);
      }
    };

    entry = { elements, cleanup };
    scrollListenerMap.set(container, entry);
  }
  return entry;
}

export function useStickyObserver<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const scrollContainerRef = useStickyScrollContainer();
  // Track the container element to re-run effect when it becomes available
  const [container, setContainer] = useState<Element | null>(null);

  // Update container state when ref becomes available
  useEffect(() => {
    const checkContainer = () => {
      const newContainer = scrollContainerRef?.current ?? null;
      if (newContainer !== container) {
        setContainer(newContainer);
      }
    };

    // Check immediately
    checkContainer();

    // Also check after a microtask in case ref is set after initial render
    const timeoutId = setTimeout(checkContainer, 0);
    return () => clearTimeout(timeoutId);
  }, [scrollContainerRef, container]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // If we have a scrollContainerRef but container is null, the ref hasn't been
    // populated yet - wait for it rather than using viewport as fallback
    if (scrollContainerRef && !container) {
      return;
    }

    const { elements, cleanup } = getScrollListener(container);
    elements.add(el);

    // Initial state check
    updateStickyState(container, elements);

    return () => {
      elements.delete(el);
      // Remove stuck attribute when unmounting
      el.removeAttribute("data-useStickyObserver-stuck");

      // Clean up scroll listener if no elements left for this container
      if (elements.size === 0) {
        cleanup();
        scrollListenerMap.delete(container);
      }
    };
  }, [container, scrollContainerRef]);

  return ref;
}
