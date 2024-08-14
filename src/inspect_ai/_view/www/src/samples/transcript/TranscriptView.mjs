// @ts-check
import { html } from "htm/preact";
import { SampleInitEventView } from "./SampleInitEventView.mjs";
import { StateEventView } from "./state/StateEventView.mjs";
import { StepEventView } from "./StepEventView.mjs";
import { SubtaskEventView } from "./SubtaskEventView.mjs";
import { ModelEventView } from "./ModelEventView.mjs";
import { LoggerEventView } from "./LoggerEventView.mjs";
import { InfoEventView } from "./InfoEventView.mjs";
import { ScoreEventView } from "./ScoreEventView.mjs";
import { FontSize } from "../../appearance/Fonts.mjs";

const kContentProtocol = "tc://";

/**
 * Renders the TranscriptView component.
 *
 * @param {Object} params - The parameters for the component.
 * @param {string} params.id - The identifier for this view
 * @param {import("../../types/log").EvalEvents} params.evalEvents - The transcript events to display.
 * @param {import("./TranscriptState.mjs").StateManager} params.stateManager - A function that updates the state with a new state object.
 * @returns {import("preact").JSX.Element} The TranscriptView component.
 */
export const TranscriptView = ({ id, evalEvents, stateManager }) => {
  // Resolve content Uris (content may be stored separately to avoid
  // repetition - it will be address with a uri)
  const resolvedEvents = resolveEventContent(evalEvents);

  const rows = resolvedEvents.map((event, index) => {
    const row = html`
      <div
        style=${{
          paddingTop: 0,
          paddingBottom: 0,
        }}
      >
        <div>${renderNode(`${id}-event${index}`, event, stateManager)}</div>
      </div>
    `;
    return row;
  });

  return html`<div
    id=${id}
    style=${{
      fontSize: FontSize.small,
      display: "grid",
      margin: "1em 0",
      width: "100%",
    }}
  >
    ${rows}
  </div>`;
};

/**
 * Renders the event based on its type.
 *
 * @param {string} id - The id for this event.
 * @param { import("../../types/log").SampleInitEvent | import("../../types/log").StateEvent | import("../../types/log").StoreEvent | import("../../types/log").ModelEvent | import("../../types/log").LoggerEvent | import("../../types/log").InfoEvent | import("../../types/log").StepEvent | import("../../types/log").SubtaskEvent| import("../../types/log").ScoreEvent} event - This event.
 * @param {import("./TranscriptState.mjs").StateManager} stateManager State manager to track state as diffs are applied
 * @returns {import("preact").JSX.Element} The rendered event.
 */
export const renderNode = (id, event, stateManager) => {
  switch (event.event) {
    case "sample_init":
      return html`<${SampleInitEventView}
        id=${id}
        event=${event}
        stateManager=${stateManager}
      />`;

    case "info":
      return html`<${InfoEventView} id=${id} event=${event} />`;

    case "logger":
      return html`<${LoggerEventView} id=${id} event=${event} />`;

    case "model":
      return html`<${ModelEventView} id=${id} event=${event} />`;

    case "score":
      return html`<${ScoreEventView} id=${id} event=${event} />`;

    case "state":
      return html`<${StateEventView}
        id=${id}
        event=${event}
        stateManager=${stateManager}
      />`;

    case "step":
      return html`<${StepEventView}
        id=${id}
        event=${event}
        stateManager=${stateManager}
      />`;

    case "store":
      return html`<${StateEventView}
        id=${id}
        event=${event}
        stateManager=${stateManager}
      />`;

    case "subtask":
      return html`<${SubtaskEventView}
        id=${id}
        event=${event}
        stateManager=${stateManager}
      />`;

    default:
      return html``;
  }
};

/**
 * Resolves event content
 *
 * @param {import("../../types/log").EvalEvents} evalEvents - The transcript events to display.
 * @returns {import("../../types/log").Events} Events with resolved content.
 */
const resolveEventContent = (evalEvents) => {
  return evalEvents.events.map((e) => {
    if (e.event === "model") {
      //@ts-ignore
      e.input = resolveValue(e.input, evalEvents);
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
 * @param {import("../../types/log").EvalEvents} evalEvents - The transcript events to display.
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
