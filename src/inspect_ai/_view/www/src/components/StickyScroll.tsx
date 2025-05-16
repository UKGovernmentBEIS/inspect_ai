import {
  CSSProperties,
  FC,
  ReactNode,
  RefObject,
  useEffect,
  useRef,
  useState,
} from "react";

interface StickyScrollProps {
  children: ReactNode;
  scrollRef: RefObject<HTMLElement | null>;
  offsetTop?: number;
  zIndex?: number;
  className?: string;
  stickyClassName?: string;
  onStickyChange?: (isSticky: boolean) => void;
}

export const StickyScroll: FC<StickyScrollProps> = ({
  children,
  scrollRef,
  offsetTop = 0,
  zIndex = 100,
  className = "",
  stickyClassName = "is-sticky",
  onStickyChange,
}) => {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [isSticky, setIsSticky] = useState(false);
  const [dimensions, setDimensions] = useState({
    width: 0,
    height: 0,
    left: 0,
    stickyTop: 0, // Store the position where the element should stick
  });

  useEffect(() => {
    const wrapper = wrapperRef.current;
    const content = contentRef.current;
    const scrollContainer = scrollRef.current;

    if (!wrapper || !content || !scrollContainer) {
      return;
    }

    // Create a sentinel element that will be positioned at the desired sticky point
    const sentinel = document.createElement("div");
    sentinel.style.position = "absolute";
    sentinel.style.top = "0px"; // Position at the top of the wrapper
    sentinel.style.left = "0";
    sentinel.style.width = "1px";
    sentinel.style.height = "1px";
    sentinel.style.pointerEvents = "none";
    wrapper.prepend(sentinel);

    // Create a width tracker element that always has the same width as the wrapper
    // This helps us know what width to apply to the fixed element
    const widthTracker = document.createElement("div");
    widthTracker.style.position = "absolute";
    widthTracker.style.top = "0";
    widthTracker.style.left = "0";
    widthTracker.style.width = "100%";
    widthTracker.style.height = "0";
    widthTracker.style.pointerEvents = "none";
    widthTracker.style.visibility = "hidden";
    wrapper.prepend(widthTracker);

    // Measure element dimensions and calculate sticky position
    const updateDimensions = () => {
      if (wrapper && scrollContainer) {
        const contentRect = content.getBoundingClientRect();
        const containerRect = scrollContainer.getBoundingClientRect();
        const trackerRect = widthTracker.getBoundingClientRect();

        // Calculate where the top of the content should be when sticky
        // This is the distance from the top of the scroll container
        // plus any additional offsetTop
        const stickyTop = containerRect.top + offsetTop;

        setDimensions({
          // Use the width tracker to get the right width that respects
          // the parent container's current width, rather than the content's width
          width: trackerRect.width,
          height: contentRect.height,
          left: trackerRect.left,
          stickyTop,
        });
      }
    };

    // Initial measurement
    updateDimensions();

    // Monitor size changes
    const resizeObserver = new ResizeObserver(() => {
      // Use animationFrame to ensure dimensions are updated after DOM has settled
      requestAnimationFrame(() => {
        updateDimensions();
        // If sticky, force a re-measurement of position to update layout
        if (isSticky) {
          handleScroll();
        }
      });
    });

    resizeObserver.observe(wrapper);
    resizeObserver.observe(scrollContainer);
    resizeObserver.observe(content);

    // Add scroll event listener for more precise control
    const handleScroll = () => {
      const sentinelRect = sentinel.getBoundingClientRect();
      const containerRect = scrollContainer.getBoundingClientRect();

      // Check if sentinel is above the top of the viewport + offset
      const shouldBeSticky = sentinelRect.top < containerRect.top + offsetTop;

      if (shouldBeSticky !== isSticky) {
        updateDimensions();
        setIsSticky(shouldBeSticky);

        if (onStickyChange) {
          onStickyChange(shouldBeSticky);
        }
      }
    };

    scrollContainer.addEventListener("scroll", handleScroll);

    // Trigger initial check
    handleScroll();

    // Clean up
    return () => {
      resizeObserver.disconnect();
      scrollContainer.removeEventListener("scroll", handleScroll);
      if (sentinel.parentNode) {
        sentinel.parentNode.removeChild(sentinel);
      }
      if (widthTracker.parentNode) {
        widthTracker.parentNode.removeChild(widthTracker);
      }
    };
  }, [scrollRef, offsetTop, onStickyChange, isSticky]);

  // Wrapper styles - this div serves as the placeholder
  // When sticky, we need to ensure the wrapper has the right dimensions
  // to prevent content jumping when the element is detached from normal flow
  const wrapperStyle: CSSProperties = {
    position: "relative",
    height: isSticky ? `${dimensions.height}px` : "auto",
    // Don't constrain width - let it flow naturally with the content
  };

  // Content styles - position at the calculated stickyTop when sticky
  // For sticky mode, use fixed positioning but maintain the original width
  const contentStyle: CSSProperties = isSticky
    ? {
        position: "fixed",
        top: `${dimensions.stickyTop}px`,
        left: `${dimensions.left}px`,
        width: `${dimensions.width}px`, // Keep explicit width to prevent expanding to 100%
        maxHeight: `calc(100vh - ${dimensions.stickyTop}px)`,
        zIndex,
      }
    : {};

  const contentClassName =
    isSticky && stickyClassName
      ? `${className} ${stickyClassName}`.trim()
      : className;

  return (
    <div ref={wrapperRef} style={wrapperStyle}>
      <div ref={contentRef} className={contentClassName} style={contentStyle}>
        {children}
      </div>
    </div>
  );
};
