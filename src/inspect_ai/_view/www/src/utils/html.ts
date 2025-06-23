/**
 * Escapes special characters in a string to make it safe for use in a CSS selector.
 */
export function escapeSelector(id: string): string {
  return id.replace(/([ #.;,?!+*~'":^$[\]()=>|/\\])/g, "\\$1");
}

export const decodeHtmlEntities = (text: string): string => {
  const parser = new DOMParser();
  const doc = parser.parseFromString(text, "text/html");
  return doc.documentElement.textContent || text;
};
