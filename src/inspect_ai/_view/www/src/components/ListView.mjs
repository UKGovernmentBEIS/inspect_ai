// @ts-check
import { html } from "htm/preact";
import { useCallback, useMemo } from "preact/hooks";
import { VirtualList } from "./VirtualList.mjs";

/**
 * @template T
 * @typedef {Object} Row extends import("./VirtualList.mjs").RowDescriptor
 * @property {T} item - The index of the current file in the list.
 * @property {number} index - The index of the current file in the list.
 * @property {number} height - The height of the row.
 */

/**
 * @template T
 * @callback Renderer
 * A function that renders a single row in the virtualized list.
 * @param {Row<T>} row - The data item corresponding to the row.
 * @param {number} index - The index of the current row.
 * @returns {import('preact').JSX.Element} A JSX element representing the row.
 */

/**
 * @template T
 * A List View component with keyboard handling and mouse behavior built in
 *
 * @param {Object} props - The component properties.
 * @param {Row<T>[]} props.rows - The row data to be rendered.
 * @param {Renderer<T>} props.renderer - The row data to be rendered.
 * @param {number} props.selectedIndex - The selected index
 * @param {(index: number) => void} props.onSelectedIndex - Function to set the selected index
 * @param {(item: T) => void} props.onShowItem - Function that will be called when an item should be shown
 * @param {Object} [props.style] - Optional styles to apply to the panel.
 *
 * @returns {import('preact').JSX.Element} The rendered component.
 */
export const ListView = ({
  rows,
  renderer,
  selectedIndex,
  onSelectedIndex,
  onShowItem,
  style,
}) => {
  /**
   * Computes an array of RowDescriptor objects based on the input rows.
   *
   * @type {import("./VirtualList.mjs").RowDescriptor[]}
   */
  const rowMap = useMemo(() => {
    return rows.reduce((values, current, index) => {
      const previous =
        values.length > 0 ? values[values.length - 1] : undefined;
      const start =
        previous === undefined ? 0 : previous.start + previous.height;
      values.push({
        index,
        height: current.height,
        start,
      });
      return values;
    }, []);
  }, [rows]);

  /**
   * Selects the previous item
   */
  const previousItem = useCallback(() => {
    onSelectedIndex(Math.max(selectedIndex - 1, 0));
  }, [selectedIndex, onSelectedIndex]);

  /**
   * Selects the next item
   */
  const nextItem = useCallback(() => {
    onSelectedIndex(Math.min(selectedIndex + 1, rows.length));
  }, [rows, selectedIndex, onSelectedIndex]);

  /**
   * Shows a specific item by its index.
   *
   * @param {number} index - The index of the item to show.
   */
  const showItem = useCallback(
    (index) => {
      onSelectedIndex(index);
      setTimeout(() => {
        const currentItem = rows[index].item;
        onShowItem(currentItem);
      }, 15);
    },
    [rows, selectedIndex, onShowItem, onSelectedIndex],
  );

  /**
   * @template T
   * A List View component with keyboard handling and mouse behavior built in
   *
   * @param {Renderer<T>} renderer - The component properties.
   * @param {number} selectedIndex - The selected index
   *
   * @returns {(row: Row<T>, index: number) => import('preact').JSX.Element} The rendered component.
   */
  const withEventHandling = (renderer, selectedIndex) => {
    return (row, index) => {
      return html` <div
        onclick=${() => {
          showItem(index);
        }}
        style=${{
          boxShadow:
            index === selectedIndex
              ? "inset 0 0 0px 2px var(--bs-focus-ring-color)"
              : undefined,
          borderBottom: "solid 1px var(--bs-light-border-subtle)",
        }}
      >
        ${renderer(row, index)}
      </div>`;
    };
  };

  /**
   * Handles keydown events
   *
   * @param {KeyboardEvent} e - The component properties.
   */
  const onkeydown = useCallback(
    (e) => {
      switch (e.key) {
        case "ArrowUp":
          previousItem();
          e.preventDefault();
          e.stopPropagation();
          return false;
        case "ArrowDown":
          nextItem();
          e.preventDefault();
          e.stopPropagation();
          return false;
        case "Enter":
          showItem(selectedIndex);
          e.preventDefault();
          e.stopPropagation();
          return false;
      }
    },
    [rows, selectedIndex],
  );

  return html` <${VirtualList}
    data=${rows}
    rowMap=${rowMap}
    renderRow=${withEventHandling(renderer, selectedIndex, onSelectedIndex)}
    style=${style}
    onkeydown=${onkeydown}
  />`;
};
