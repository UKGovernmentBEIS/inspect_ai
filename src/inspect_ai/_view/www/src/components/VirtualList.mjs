import { html } from "htm/preact";
import { useRef, useState, useEffect } from "preact/hooks";
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
 * @param {number} [props.overscanCount=10] - Number of extra rows to render above and below the visible area
 * @param {number} [props.estimatedRowHeight=50] - Estimated height of each row before measurement
 * @param {boolean} [props.sync] - If true, forces a re-render on scroll
 * @param {import("preact").RefObject<HTMLElement>} [props.scrollRef] - Optional ref to use as scroll container
 * @param {Object} [props.props] - Additional props to be spread onto the container element
 * @returns {preact.VNode} The virtual list component
 */
export function VirtualList({
  data,
  renderRow,
  overscanCount = 10,
  estimatedRowHeight = 50,
  sync,
  scrollRef,
  ...props
}) {
  const [height, setHeight] = useState(0);
  const [offset, setOffset] = useState(0);
  const [rowHeights, setRowHeights] = useState(new Map());
  const [totalHeight, setTotalHeight] = useState(0);

  const baseRef = useRef(null);
  const containerRef = useRef(null);
  const rowRefs = useRef(new Map());

  // Function to get row height (measured or estimated)
  const getRowHeight = (index) => {
    return rowHeights.get(index) || estimatedRowHeight;
  };

  // Calculate row positions based on current heights
  const calculateRowPositions = () => {
    let currentPosition = 0;
    const positions = new Map();
    
    for (let i = 0; i < data.length; i++) {
      positions.set(i, currentPosition);
      currentPosition += getRowHeight(i);
    }
    
    return positions;
  };

  // Measure rendered rows and update heights if needed
  const measureRows = () => {
    let heightsUpdated = false;
    const newHeights = new Map(rowHeights);

    rowRefs.current.forEach((element, index) => {
      if (element) {
        const measuredHeight = element.offsetHeight;
        if (measuredHeight && measuredHeight !== newHeights.get(index)) {
          newHeights.set(index, measuredHeight);
          heightsUpdated = true;
        }
      }
    });

    if (heightsUpdated) {
      setRowHeights(newHeights);
      updateTotalHeight(newHeights);
    }
  };

  // Update total height based on current row heights
  const updateTotalHeight = (heights = rowHeights) => {
    let total = 0;
    for (let i = 0; i < data.length; i++) {
      total += heights.get(i) || estimatedRowHeight;
    }
    setTotalHeight(total);
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

  // Setup resize listener
  useEffect(() => {
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  // Measure rows after render
  useEffect(() => {
    measureRows();
  });

  // Calculate visible range
  const rowPositions = calculateRowPositions();
  
  const findRowAtOffset = (targetOffset) => {
    let low = 0;
    let high = data.length - 1;
    
    while (low <= high) {
      const mid = Math.floor((low + high) / 2);
      const rowStart = rowPositions.get(mid) || 0;
      const rowEnd = rowStart + getRowHeight(mid);
      
      if (targetOffset >= rowStart && targetOffset < rowEnd) {
        return mid;
      }
      
      if (targetOffset < rowStart) {
        high = mid - 1;
      } else {
        low = mid + 1;
      }
    }
    
    return 0;
  };

  const firstVisibleIdx = findRowAtOffset(offset);
  const lastVisibleIdx = findRowAtOffset(offset + height);

  // Calculate range of rows to render including overscan
  const start = Math.max(0, firstVisibleIdx - overscanCount);
  const end = Math.min(data.length, lastVisibleIdx + overscanCount);
  const selection = data.slice(start, end);

  const style_inner = {
    position: "relative",
    overflow: "hidden",
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

  return html`
    <div onscroll=${handleScroll} ref=${baseRef} ...${props}>
      <div style=${{ ...style_inner, height: `${totalHeight}px` }}>
        <div style=${{ ...style_content, top: `${top}px` }} ref=${containerRef}>
          ${selection.map((item, index) => {
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
          })}
        </div>
      </div>
    </div>
  `;
}