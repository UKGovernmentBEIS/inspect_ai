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

// Determine the capabilities
// If this is vscode, check for the version meta
// so we know it supports downloads
export const isVscode = () => {
  const bodyEl = document.querySelector("body");
  return !!bodyEl.getAttributeNames().find((attr) => {
    return attr.includes("data-vscode-");
  });
};
