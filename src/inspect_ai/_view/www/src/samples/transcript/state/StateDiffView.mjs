// @ts-check
/// <reference path="../../../types/jsondiffpatch.d.ts" />

import { html } from "htm/preact";
import { diff } from "jsondiffpatch";
import { format } from "jsondiffpatch/formatters/html";

/**
 * Renders a view displaying a list of state changes.
 *
 * @param {Object} props - The properties for the component.
 * @param {Object} props.starting - The list of changes to be displayed.
 * @param {Object} props.ending - The list of changes to be displayed.
 * @param {Record<string, string>} [props.style] - Optional custom styles for the view container.
 * @returns {import("preact").JSX.Element | undefined} The component.
 */
export const StateDiffView = ({ starting, ending, style }) => {
  const changes = diff(unescapeNewlines(starting), unescapeNewlines(ending));
  const html_result = format(changes);
  return html`<div
    dangerouslySetInnerHTML=${{ __html: unescapeNewlines(html_result) }}
    style=${{ style }}
  ></div>`;
};
function unescapeNewlines(obj) {
  if (typeof obj === "string") {
    return obj.replace(/\\n/g, "\n");
  } else if (typeof obj === "object") {
    for (let key in obj) {
      obj[key] = unescapeNewlines(obj[key]);
    }
  }
  return obj;
}
