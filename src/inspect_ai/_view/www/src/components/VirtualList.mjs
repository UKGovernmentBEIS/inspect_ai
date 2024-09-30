// @ts-check
// preact-virtual-list.mjs

import { html, Component } from "htm/preact";
import { createRef } from "preact";
import { throttle } from "../utils/sync.mjs";


/**
 * @typedef {Object} RowDescriptor
 * @property {number} index - The index of the current file in the list.
 * @property {number} height - The height of the row, defined by `kRowHeight`.
 * @property {number} start - The starting position of the row, calculated based on the previous row.
 */

/**
 * @template T
 * @callback RowRenderer
 * A function that renders a single row in the virtualized list.
 * @param {T} item - The data item corresponding to the row.
 * @param {number} index - The index of the current row.
 * @returns {import('preact').JSX.Element} A JSX element representing the row.
 */


const STYLE_INNER =
  "position:relative; overflow:hidden; width:100%; min-height:100%;";
const STYLE_CONTENT =
  "position:absolute; top:0; left:0; height:100%; width:100%; overflow:visible;";

/**
 * @template T
 * VirtualList component renders a large dataset using virtualization to optimize performance.
 * It only renders visible items based on the user's scroll position.
 *
 * @class
 * @extends Component
 */
export class VirtualList extends Component {
  /**
   * Creates an instance of VirtualList.
   * @param {Object} props - The properties passed to the component.
   * @param {Array<T>} props.data - Array of data items to render.
   * @param {Array<RowDescriptor>} props.rowMap - Array of objects mapping row positions.
   * @param {RowRenderer<T>} props.renderRow - Function to render a single row. Receives the item and index as arguments.
   * @param {number} [props.overscanCount=10] - Number of extra rows to render before and after the visible area for smoother scrolling.
   * @param {boolean} [props.sync=false] - Forces a re-render on scroll if set to true.
   */
  constructor(props) {
    super(props);
    this.state = {
      height: 0,
      offset: 0,
    };
    this.resize = this.resize.bind(this);
    this.handleScroll = throttle(this.handleScroll.bind(this), 100);
    this.containerRef = createRef();
  }

  /**
  * Resizes the component based on the current height of the container.
  * Updates the height state if the container height has changed.
  * @private
  */
  resize() {
    if (this.base instanceof HTMLElement) {
      if (this.state.height !== this.base.offsetHeight) {
        this.setState({ height: this.base.offsetHeight });
      }
    }
  }

  /**
   * Handles the scroll event and updates the offset state.
   * Forces a re-render if the sync prop is true.
   * @private
   */
  handleScroll() {
    if (this.base instanceof HTMLElement && this.base) {
      this.setState({ offset: this.base.scrollTop });
    }
    if (this.props.sync) {
      this.forceUpdate();
    }
  }

  /**
   * Lifecycle method called after the component updates. Ensures the resize logic is applied.
   */
  componentDidUpdate() {
    this.resize();
  }

  /**
   * Lifecycle method called when the component mounts.
   * Adds a window resize event listener to handle resizing.
   */
  componentDidMount() {
    this.resize();
    window.addEventListener("resize", this.resize);
  }

  /**
   * Lifecycle method called before the component unmounts.
   * Removes the window resize event listener.
   */
  componentWillUnmount() {
    window.removeEventListener("resize", this.resize);
  }

  /**
   * Renders the virtualized list based on the current scroll position and the row data.
   *
   * @param {Object} props - Component properties.
   * @param {Array<Object>} props.data - Array of data items to render.
   * @param {Array<Object>} props.rowMap - Array of objects that map row positions (start and height).
   * @param {Function} props.renderRow - Function to render a single row. Receives the item and index as arguments.
   * @param {number} [props.overscanCount=10] - Number of extra rows to render for smooth scrolling.
   * @param {Object} state - Component state.
   * @param {number} [state.offset=0] - The current scroll offset.
   * @param {number} [state.height=0] - The current height of the visible area.
   * @returns {import("preact").JSX.Element} The virtualized list of items to be rendered.
   */
  render(
    { data, rowMap, renderRow, overscanCount = 10, ...props },
    { offset = 0, height = 0 },
  ) {
    // Compute the start and ending rows
    const firstVisibleIdx = rowMap.findIndex((row) => {
      return row.start + row.height >= offset;
    });
    const firstIndex = firstVisibleIdx > -1 ? firstVisibleIdx : 0;

    const lastVisibleIdx = rowMap.findIndex((row) => {
      return row.start + row.height >= offset + height;
    });
    const lastIndex = lastVisibleIdx > -1 ? lastVisibleIdx : rowMap.length - 1;

    // Compute the total height
    const lastRow = rowMap[rowMap.length - 1];
    const totalHeight = lastRow ? lastRow.start + lastRow.height : 0;

    // Compute the visible rows (including overscan)
    let visibleRowCount = lastIndex - firstIndex;
    if (overscanCount) {
      visibleRowCount += overscanCount;
    }

    // Account for overscan
    const start = firstVisibleIdx;
    const end = Math.min(data.length, start + visibleRowCount);

    const selection = data.slice(start, end);

    // const firstRow
    const top = firstVisibleIdx !== -1 ? rowMap[firstVisibleIdx].start : 0;
    const rows = html`<div onscroll=${this.handleScroll} ...${props}>
      <div style=${`${STYLE_INNER} height:${totalHeight}px;`}>
        <div style=${`${STYLE_CONTENT} top:${top}px;`} ref=${this.containerRef}>
          ${selection.map((item, index) => {
      const component = renderRow(item, start + index);

      return html`<div key=${`list-item-${start + index}`}>
              ${component}
            </div>`;
    })}
        </div>
      </div>
    </div>`;
    return rows;
  }
}
