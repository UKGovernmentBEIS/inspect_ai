import { RefObject, useEffect, useRef, useState } from "react";

interface UseStickyRefOptions {
  scrollRef: RefObject<HTMLElement | null>;
  offsetTop?: number;
  enableSmoothing?: boolean;
}

export const useStickyRef = ({
  scrollRef,
  offsetTop = 0,
}: UseStickyRefOptions) => {
  const [offsetY, setOffsetY] = useState(0);
  const elementRef = useRef<HTMLDivElement>(null);
  const naturalPositionRef = useRef<number | null>(null);
  const isPinnedRef = useRef(false);

  useEffect(() => {
    const element = elementRef.current;
    const scrollContainer = scrollRef?.current;

    if (!element || !scrollContainer) return;

    // Store the element's initial position in the document
    // This position is fixed and won't change with scrolling
    const getNaturalPosition = () => {
      const elementRect = element.getBoundingClientRect();
      const containerRect = scrollContainer.getBoundingClientRect();

      // Get the accurate position accounting for margins and padding between elements
      let currentElement: HTMLElement | null = element;
      let totalOffset = 0;
      
      // Start with the scroll container's padding-top, which affects the starting point
      const containerStyle = window.getComputedStyle(scrollContainer);
      totalOffset += parseFloat(containerStyle.paddingTop) || 0;

      // Walk up the DOM tree, collecting margins and padding until we reach the scroll container
      while (
        currentElement &&
        currentElement !== scrollContainer &&
        currentElement.parentElement
      ) {
        const computedStyle = window.getComputedStyle(currentElement);
        
        if (currentElement !== element) {
          // Add margins of parent elements
          totalOffset += parseFloat(computedStyle.marginTop) || 0;
          totalOffset += parseFloat(computedStyle.marginBottom) || 0;
          
          // Add padding of parent elements
          totalOffset += parseFloat(computedStyle.paddingTop) || 0;
          totalOffset += parseFloat(computedStyle.paddingBottom) || 0;
        }

        // Move up to the parent element
        currentElement = currentElement.parentElement;
        
        // If we're at the parent of the scroll container, include its padding as well
        if (currentElement && currentElement.contains(scrollContainer) && currentElement !== scrollContainer) {
          const parentStyle = window.getComputedStyle(currentElement);
          totalOffset += parseFloat(parentStyle.paddingTop) || 0;
        }
      }

      // Calculate the position offset that accounts for all spacing elements
      return elementRect.top - containerRect.top + totalOffset;
    };
    naturalPositionRef.current = getNaturalPosition();

    let animationFrameId: number | null = null;

    const handleScroll = () => {
      if (animationFrameId) {
        cancelAnimationFrame(animationFrameId);
      }

      animationFrameId = requestAnimationFrame(() => {
        if (!element || !scrollContainer || naturalPositionRef.current === null)
          return;

        // Get the current scroll position
        const scrollTop = scrollContainer.scrollTop;

        // Calculate the element's current position relative to the viewport
        // This is where the element would naturally be without any transformation
        const elementTopRelativeToContainer =
          naturalPositionRef.current - scrollTop;

        console.log({
          position: naturalPositionRef.current,
          scrollTop,
          elementTopRelativeToContainer,
        });

        if (elementTopRelativeToContainer < offsetTop) {
          // Element would be above our threshold, so pin it
          setOffsetY(offsetTop - elementTopRelativeToContainer);
          isPinnedRef.current = true;
        } else {
          // Element is below our threshold, no offset needed
          setOffsetY(0);
          isPinnedRef.current = false;
        }

        animationFrameId = null;
      });
    };

    // Handle window resize which might change element positions
    const handleResize = () => {
      // Recalculate position on resize
      naturalPositionRef.current = getNaturalPosition();
      handleScroll();
    };

    scrollContainer.addEventListener("scroll", handleScroll);
    window.addEventListener("resize", handleResize);

    // Run once after mount to handle initial state
    handleScroll();

    return () => {
      scrollContainer.removeEventListener("scroll", handleScroll);
      window.removeEventListener("resize", handleResize);

      if (animationFrameId) {
        cancelAnimationFrame(animationFrameId);
      }
    };
  }, [scrollRef, offsetTop]);

  // Return the ref and styles to be applied
  return {
    ref: elementRef,
    style: {
      transform: `translateY(${offsetY}px)`,
      willChange: "transform",
    },
  };
};
