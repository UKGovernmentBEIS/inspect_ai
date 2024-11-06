// preact-virtual-list.mjs

import { html, Component } from "htm/preact";
import { createRef } from "preact";
import { throttle } from "../../utils/sync.mjs";

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

export class VirtualList extends Component {
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
    // @ts-ignore
    if (this.state.height !== this.base.offsetHeight) {
      // @ts-ignore
      this.setState({ height: this.base.offsetHeight });
    }
  }

  handleScroll() {
    if (this.base) {
      // @ts-ignore
      this.setState({ offset: this.base.scrollTop });
    }
    if (this.props.sync) {
      this.forceUpdate();
    }
  }

  componentDidUpdate() {
    this.resize();
  }

  componentDidMount() {
    this.resize();
    window.addEventListener("resize", this.resize);
  }

  componentWillUnmount() {
    window.removeEventListener("resize", this.resize);
  }

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
