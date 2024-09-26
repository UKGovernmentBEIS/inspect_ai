// @ts-check
import { html } from "htm/preact";
import { TranscriptView } from "./transcript/TranscriptView.mjs";

const kContentProtocol = "tc://";

/**
 * Renders the SampleTranscript component.
 *
 * @param {Object} params - The parameters for the component.
 * @param {string} params.id - The id of this component
 * @param {import("../types/log").EvalEvents} params.evalEvents - The transcript to display.
 * @returns {import("preact").JSX.Element} The SampleTranscript component.
 */
export const SampleTranscript = ({ id, evalEvents }) => {
  // Resolve content Uris (content may be stored separately to avoid
  // repetition - it will be address with a uri)
  const denormalizedEvents = resolveEventContent(evalEvents);

  return html`<${TranscriptView} id=${id} events=${denormalizedEvents} />`;
};

/**
 * Resolves event content
 *
 * @param {import("../types/log").EvalEvents} evalEvents - The transcript events to display.
 * @returns {import("../types/log").Events} Events with resolved content.
 */
const resolveEventContent = (evalEvents) => {
  return /** @type {import("../types/log").Events} */ (
    evalEvents.events.map((e) => {
      return resolveValue(e, evalEvents);
    })
  );
};

/**
 * Resolves individual value
 *
 * @param {unknown} value - The value to resolve.
 * @param {import("../types/log").EvalEvents} evalEvents - The transcript events to display.
 * @returns {unknown} Value with resolved content.
 */
const resolveValue = (value, evalEvents) => {
  if (Array.isArray(value)) {
    return value.map((v) => resolveValue(v, evalEvents));
  } else if (value && typeof value === "object") {
    /** @type {Record<string, unknown>} */
    const resolvedObject = {};
    for (const key of Object.keys(value)) {
      //@ts-ignore
      resolvedObject[key] = resolveValue(value[key], evalEvents);
    }
    return resolvedObject;
  } else if (typeof value === "string") {
    if (value.startsWith(kContentProtocol)) {
      return evalEvents.content[value.replace(kContentProtocol, "")];
    }
  }
  return value;
};
