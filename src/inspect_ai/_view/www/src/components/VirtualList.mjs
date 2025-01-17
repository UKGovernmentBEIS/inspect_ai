import { html } from "htm/preact";
import { useRef, useState, useEffect, useMemo } from "preact/hooks";
import { forwardRef, useImperativeHandle } from "preact/compat";
import { throttle } from "../utils/sync.mjs";

/**
 * A virtualized list component that efficiently renders large lists by only
 * rendering the items that are currently visible in the viewport.
 * Supports dynamic row heights that are measured after rendering.
 *
 * @template T
 * @param {Object} props - The component props
 * @param {T[]} props.data - Array of items to be rendered in the list
 * @param {(item: T, index: number) => preact.VNode} props.renderRow - Function to render each row
 * @param {number} [props.overscanCount=15] - Number of extra rows to render above and below the visible area
 * @param {number} [props.estimatedRowHeight=50] - Estimated height of each row before measurement
 * @param {boolean} [props.sync=false] - If true, forces a re-render on scroll
 * @param {import("preact").RefObject<HTMLElement>} [props.scrollRef] - Optional ref for the scroll container
 * @param {import("preact").Ref<{ scrollToIndex: (index: number) => void }>} ref - Ref object exposing the list's methods
 * @returns {preact.VNode} The virtualized list component
 */
export const VirtualList = forwardRef(
  (
    /** @type {props} */ {
      data,
      renderRow,
      overscanCount = 15,
      estimatedRowHeight = 50,
      sync = false,
      scrollRef,
      ...props
    },
    ref,
  ) => {
    const [height, setHeight] = useState(0);
    const [offset, setOffset] = useState(0);

    const [listMetrics, setListMetrics] = useState({
      rowHeights: new Map(),
      totalHeight: data.length * estimatedRowHeight,
    });

    const baseRef = useRef(null);
    const containerRef = useRef(null);
    const rowRefs = useRef(new Map());

    // Function to get row height (measured or estimated)
    const getRowHeight = (index) => {
      return listMetrics.rowHeights.get(index) || estimatedRowHeight;
    };

    // Calculate row positions based on current heights
    const rowPositions = useMemo(() => {
      let currentPosition = 0;
      const positions = new Map();

      for (let i = 0; i < data.length; i++) {
        positions.set(i, currentPosition);
        currentPosition += getRowHeight(i);
      }

      return positions;
    }, [listMetrics.rowHeights, data.length]);

    // Expose scrollToIndex method via ref
    useImperativeHandle(
      ref,
      () => ({
        focus: () => {
          baseRef.current;
        },
        scrollToIndex: (index, direction) => {
          const scrollElement = scrollRef?.current || baseRef.current;
          if (!scrollElement || index < 0 || index >= data.length) return;

          const currentScrollTop = scrollElement.scrollTop;
          const viewportHeight = scrollElement.offsetHeight;

          // Get position and height of target row
          const rowTop = rowPositions.get(index) || 0;
          const rowHeight = getRowHeight(index);
          const rowBottom = rowTop + rowHeight;

          // If this is already visible, don't scroll
          const isVisible =
            rowTop >= currentScrollTop &&
            rowBottom <= currentScrollTop + viewportHeight;
          if (isVisible) {
            return;
          }

          // Calculate new scroll position based on direction
          let newScrollTop;
          if (direction === "up") {
            // Align top of element with top of viewport
            newScrollTop = rowTop;
          } else {
            // Align bottom of element with bottom of viewport
            newScrollTop = rowBottom - viewportHeight;
          }

          // Clamp scroll position to valid range
          newScrollTop = Math.max(
            0,
            Math.min(newScrollTop, listMetrics.totalHeight - viewportHeight),
          );
          scrollElement.scrollTop = newScrollTop;
        },
      }),
      [rowPositions, data.length],
    );

    // Measure rendered rows and update heights if needed
    const measureRows = () => {
      // Keep track of updated heights
      let updates = [];

      rowRefs.current.forEach((element, index) => {
        if (element) {
          const measuredHeight = element.offsetHeight;
          // If the measured height is different, schedule an update
          if (
            measuredHeight &&
            measuredHeight !== listMetrics.rowHeights.get(index)
          ) {
            updates.push([index, measuredHeight]);
          }
        }
      });

      // If no rows changed, do nothing
      if (updates.length === 0) return;

      // Create a new Map of rowHeights so we don't mutate state directly
      const newHeights = new Map(listMetrics.rowHeights);
      updates.forEach(([index, height]) => {
        newHeights.set(index, height);
      });

      // Recompute total height only once
      let newTotalHeight = 0;
      for (let i = 0; i < data.length; i++) {
        newTotalHeight += newHeights.get(i) || estimatedRowHeight;
      }

      // Now update our single state object in one go:
      setListMetrics({
        rowHeights: newHeights,
        totalHeight: newTotalHeight,
      });
    };

    // Handle container resize
    const resize = () => {
      const scrollElement = scrollRef?.current || baseRef.current;
      if (scrollElement && height !== scrollElement.offsetHeight) {
        setHeight(scrollElement.offsetHeight);
      }
    };

    // Handle scroll with throttling
    const handleScroll = throttle(() => {
      const scrollElement = scrollRef?.current || baseRef.current;
      if (scrollElement) {
        setOffset(scrollElement.scrollTop);
      }
      if (sync) {
        setOffset((prev) => prev);
      }
    }, 100);

    // Setup scroll and resize listeners
    useEffect(() => {
      resize();
      const scrollElement = scrollRef?.current || baseRef.current;

      if (scrollElement) {
        scrollElement.addEventListener("scroll", handleScroll);
        window.addEventListener("resize", resize);

        return () => {
          scrollElement.removeEventListener("scroll", handleScroll);
          window.removeEventListener("resize", resize);
        };
      }
    }, [scrollRef?.current]);

    // Measure rows after render
    useEffect(() => {
      measureRows();
    });

    const findRowAtOffset = (targetOffset) => {
      if (targetOffset <= 0) return 0;
      if (targetOffset >= listMetrics.totalHeight) return data.length - 1;

      let low = 0;
      let high = data.length - 1;
      let lastValid = 0;

      while (low <= high) {
        const mid = Math.floor((low + high) / 2);
        const rowStart = rowPositions.get(mid) || 0;

        if (rowStart <= targetOffset) {
          lastValid = mid;
          low = mid + 1;
        } else {
          high = mid - 1;
        }
      }
      return lastValid;
    };

    const firstVisibleIdx = findRowAtOffset(offset);
    const lastVisibleIdx = findRowAtOffset(offset + height);

    // Calculate range of rows to render including overscan
    const start = Math.max(0, firstVisibleIdx - overscanCount);
    const end = Math.min(data.length, lastVisibleIdx + overscanCount);

    // Memoize the rendered rows to prevent unnecessary re-renders
    const renderedRows = useMemo(() => {
      const selection = data.slice(start, end);
      return selection.map((item, index) => {
        const actualIndex = start + index;
        return html`
          <div
            key=${`list-item-${actualIndex}`}
            ref=${(el) => {
              if (el) {
                rowRefs.current.set(actualIndex, el);
              } else {
                rowRefs.current.delete(actualIndex);
              }
            }}
          >
            ${renderRow(item, actualIndex)}
          </div>
        `;
      });
    }, [data, start, end, renderRow]);

    const style_inner = {
      position: "relative",
      overflow: scrollRef?.current ? "visible" : "hidden",
      width: "100%",
      minHeight: "100%",
    };

    const style_content = {
      position: "absolute",
      top: 0,
      left: 0,
      height: "100%",
      width: "100%",
      overflow: "visible",
    };

    const top = rowPositions.get(start) || 0;

    // Only attach onscroll to baseRef if no scrollRef is provided
    const scrollProps = scrollRef ? {} : { onscroll: handleScroll };

    return html`
      <div ref=${baseRef} ...${props} ...${scrollProps}>
        <div
          style=${{ ...style_inner, height: `${listMetrics.totalHeight}px` }}
        >
          <div
            style=${{ ...style_content, top: `${top}px` }}
            ref=${containerRef}
          >
            ${renderedRows}
          </div>
        </div>
      </div>
    `;
  },
);
