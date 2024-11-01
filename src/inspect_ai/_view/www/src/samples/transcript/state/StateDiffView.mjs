// @ts-check
/// <reference path="../../../types/jsondiffpatch.d.ts" />

import { html } from "htm/preact";
import { diff } from "jsondiffpatch";
import { format } from "jsondiffpatch/formatters/html";

/**
 * Renders a view displaying a list of state changes.
 *
 * @param {Object} props - The properties for the component.
 * @param {Object} props.before - The object in its before state
 * @param {Object} props.after - The object in its before state
 * @param {Record<string, string>} [props.style] - Optional custom styles for the view container.
 * @returns {import("preact").JSX.Element | undefined} The component.
 */
export const StateDiffView = ({ before, after, style }) => {
  // Diff the objects and render the diff
  const state_diff = diff(sanitizeKeys(before), sanitizeKeys(after));

  const html_result = format(state_diff) || "Unable to render differences";
  return html`<div
    dangerouslySetInnerHTML=${{ __html: unescapeNewlines(html_result) }}
    style=${{ ...style }}
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

function sanitizeKeys(obj) {
  if (typeof obj !== "object" || obj === null) {
    return obj;
  }

  if (Array.isArray(obj)) {
    return obj.map(sanitizeKeys);
  }

  return Object.fromEntries(
    Object.entries(obj).map(([key, value]) => [
      key.replace(/</g, "&lt;").replace(/>/g, "&gt;"),
      sanitizeKeys(value),
    ]),
  );
}
