/**
 * Enum for renderer bucket priorities.
 * Determines the order in which renderers are applied.
 *
 * @enum {number}
 */
export const Buckets = {
  first: 0,
  intermediate: 10,
  final: 1000,
};

/**
 * @typedef {Object} ContentRenderer
 * @property {number} bucket - Priority bucket for the renderer. Lower numbers are higher priority.
 * @property {(content: any) => boolean} canRender - Determines if the renderer can handle the entry.
 * @property {(id: string, content: any) => { rendered: import("preact").JSX.Element | import("preact").JSX.Element[] | string }} render
 *   - Function that renders the entry. Returns an object containing the rendered content and optional after-body content.
 */
