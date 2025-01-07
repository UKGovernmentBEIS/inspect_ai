import { html } from "htm/preact";
import { useRef, useState, useEffect } from "preact/hooks";
import { throttle } from "../utils/sync.mjs";

/**
 * @typedef {Object} RowMapItem
 * @property {number} start - The starting position of the row in pixels
 * @property {number} height - The height of the row in pixels
 */

/**
 * A virtualized list component that efficiently renders large lists by only
 * rendering the items that are currently visible in the viewport.
 *
 * @template T
 * @param {Object} props - The component props
 * @param {T[]} props.data - Array of items to be rendered in the list
 * @param {RowMapItem[]} props.rowMap - Array of objects containing the start position and height of each row
 * @param {(item: T, index: number) => preact.VNode} props.renderRow - Function to render each row
 * @param {number} [props.overscanCount=10] - Number of extra rows to render above and below the visible area
 * @param {boolean} [props.sync] - If true, forces a re-render on scroll
 * @param {Object} [props.props] - Additional props to be spread onto the container element
 * @returns {preact.VNode} The virtual list component
 */
export function VirtualList({
  data,
  rowMap,
  renderRow,
  overscanCount = 10,
  sync,
  ...props
}) {
  /** @type {[number, (height: number | ((prev: number) => number)) => void]} */
  const [height, setHeight] = useState(0);

  /** @type {[number, (offset: number | ((prev: number) => number)) => void]} */
  const [offset, setOffset] = useState(0);

  /** @type {import("preact").RefObject<HTMLElement>} */
  const baseRef = useRef(null);

  /** @type {import("preact").RefObject<HTMLElement>} */
  const containerRef = useRef(null);

  /**
   * Updates the height state if the base element's height has changed
   * @type {() => void}
   */
  const resize = () => {
    if (baseRef.current && height !== baseRef.current.offsetHeight) {
      setHeight(baseRef.current.offsetHeight);
    }
  };

  /**
   * Handles scroll events with throttling
   * @type {Function}
   */
  const handleScroll = throttle(() => {
    if (baseRef.current) {
      setOffset(baseRef.current.scrollTop);
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

  // Update on height changes
  useEffect(() => {
    resize();
  }, [height]);

  // Find the first visible row index
  const firstVisibleIdx = rowMap.findIndex((row) => {
    return row.start + row.height >= offset;
  });
  const firstIndex = firstVisibleIdx > -1 ? firstVisibleIdx : 0;

  // Find the last visible row index
  const lastVisibleIdx = rowMap.findIndex((row) => {
    return row.start + row.height >= offset + height;
  });
  const lastIndex = lastVisibleIdx > -1 ? lastVisibleIdx : rowMap.length - 1;

  // Calculate total height of all rows
  const lastRow = rowMap[rowMap.length - 1];
  const totalHeight = lastRow ? lastRow.start + lastRow.height : 0;

  // Calculate number of rows to render including overscan
  let visibleRowCount = lastIndex - firstIndex;
  if (overscanCount) {
    visibleRowCount += overscanCount;
  }

  // Calculate the range of rows to render
  const start = firstVisibleIdx;
  const end = Math.min(data.length, start + visibleRowCount);
  const selection = data.slice(start, end);

  /** @type {import("preact").JSX.CSSProperties} */
  const style_inner = {
    position: "relative",
    overflow: "hidden",
    width: "100%",
    minHeight: "100%",
  };

  /** @type {import("preact").JSX.CSSProperties} */
  const style_content = {
    position: "absolute",
    top: 0,
    left: 0,
    height: "100%",
    width: "100%",
    overflow: "visible",
  };

  const top = firstVisibleIdx !== -1 ? rowMap[firstVisibleIdx].start : 0;

  return html`
    <div onscroll=${handleScroll} ref=${baseRef} ...${props}>
      <div style=${{ ...style_inner, height: `${totalHeight}px` }}>
        <div style=${{ ...style_content, top: `${top}px` }} ref=${containerRef}>
          ${selection.map((item, index) => {
            const component = renderRow(item, start + index);
            return html`
              <div key=${`list-item-${start + index}`}>${component}</div>
            `;
          })}
        </div>
      </div>
    </div>
  `;
}
