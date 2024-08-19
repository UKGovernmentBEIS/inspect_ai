// @ts-check
import { html } from "htm/preact";
import { TranscriptView } from "./transcript/TranscriptView.mjs";
import { initStateManager } from "./transcript/TranscriptState.mjs";

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
  const stateManager = initStateManager();

  // Resolve content Uris (content may be stored separately to avoid
  // repetition - it will be address with a uri)
  const denormalizedEvents = resolveEventContent(evalEvents);

  return html`<${TranscriptView}
    id=${id}
    events=${denormalizedEvents}
    stateManager=${stateManager}
  />`;
};

/**
 * Resolves event content
 *
 * @param {import("../types/log").EvalEvents} evalEvents - The transcript events to display.
 * @returns {import("../types/log").Events} Events with resolved content.
 */
const resolveEventContent = (evalEvents) => {
  return evalEvents.events.map((e) => {
    if (e.event === "model") {
      //@ts-ignore
      e.input = resolveValue(e.input, evalEvents);
      //@ts-ignore
      e.call = resolveValue(e.call, evalEvents);
      //@ts-ignore
      e.output = resolveValue(e.output, evalEvents);
    } else if (e.event === "state") {
      e.changes = e.changes.map((change) => {
        change.value = resolveValue(change.value, evalEvents);
        return change;
      });
    } else if (e.event === "sample_init") {
      //@ts-ignore
      e.state["messages"] = resolveValue(e.state["messages"], evalEvents);
    }
    return e;
  });
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
