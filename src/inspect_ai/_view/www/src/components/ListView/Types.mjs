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
