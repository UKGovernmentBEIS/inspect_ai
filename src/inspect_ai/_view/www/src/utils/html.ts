/**
 * Escapes special characters in a string to make it safe for use in a CSS selector.
 */
export function escapeSelector(id: string): string {
  return id.replace(/([ #.;,?!+*~'":^$[\]()=>|/\\])/g, "\\$1");
}
