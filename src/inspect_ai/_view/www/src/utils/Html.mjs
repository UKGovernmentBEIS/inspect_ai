// @ts-check

/**
 * Escapes special characters in a string to make it safe for use in a CSS selector.
 *
 * @param {string} id - The string (usually an id or class name) to be escaped for use in a CSS selector.
 * @returns {string} - The escaped string safe for use in `querySelector` or `querySelectorAll`.
 */
export function escapeSelector(id) {
  return id.replace(/([ #.;,?!+*~'":^$[\]()=>|/\\])/g, "\\$1");
}
