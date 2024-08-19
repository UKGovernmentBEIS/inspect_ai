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
import { ToolEventView } from "./ToolEventView.mjs";
import { FontSize } from "../../appearance/Fonts.mjs";

/**
 * Renders the TranscriptView component.
 *
 * @param {Object} params - The parameters for the component.
 * @param {string} params.id - The identifier for this view
 * @param {import("../../types/log").Events} params.events - The transcript events to display.
 * @param {import("./TranscriptState.mjs").StateManager} params.stateManager - A function that updates the state with a new state object.
 * @returns {import("preact").JSX.Element} The TranscriptView component.
 */
export const TranscriptView = ({ id, events, stateManager }) => {
  // Normalize Events themselves
  const resolvedEvents = fixupEventStream(events);

  let depth = 0;
  const rows = resolvedEvents.map((event, index) => {
    const row = html`
      <div
        style=${{
          paddingTop: 0,
          paddingBottom: 0,
        }}
      >
        <div>
          ${renderNode(
            `${id}-event${index}`,
            event,
            Math.max(depth - 1, 0),
            stateManager,
          )}
        </div>
      </div>
    `;

    if (event.event === "step") {
      if (event.action === "end") {
        depth = depth - 1;
      } else {
        depth = depth + 1;
      }
    }

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
 * @param { import("../../types/log").SampleInitEvent | import("../../types/log").StateEvent | import("../../types/log").StoreEvent | import("../../types/log").ModelEvent | import("../../types/log").LoggerEvent | import("../../types/log").InfoEvent | import("../../types/log").StepEvent | import("../../types/log").SubtaskEvent| import("../../types/log").ScoreEvent | import("../../types/log").ToolEvent} event - This event.
 * @param {number} depth - How deeply nested this node is
 * @param {import("./TranscriptState.mjs").StateManager} stateManager State manager to track state as diffs are applied
 * @returns {import("preact").JSX.Element} The rendered event.
 */
export const renderNode = (id, event, depth, stateManager) => {
  switch (event.event) {
    case "sample_init":
      return html`<${SampleInitEventView}
        id=${id}
        depth=${depth}
        event=${event}
        stateManager=${stateManager}
      />`;

    case "info":
      return html`<${InfoEventView} id=${id} depth=${depth} event=${event} />`;

    case "logger":
      return html`<${LoggerEventView}
        id=${id}
        depth=${depth}
        event=${event}
      />`;

    case "model":
      return html`<${ModelEventView} id=${id} depth=${depth} event=${event} />`;

    case "score":
      return html`<${ScoreEventView} id=${id} depth=${depth} event=${event} />`;

    case "state":
      return html`<${StateEventView}
        id=${id}
        depth=${depth}
        event=${event}
        stateManager=${stateManager}
      />`;

    case "step":
      return html`<${StepEventView}
        id=${id}
        depth=${depth}
        event=${event}
        stateManager=${stateManager}
      />`;

    case "store":
      return html`<${StateEventView}
        id=${id}
        depth=${depth}
        event=${event}
        stateManager=${stateManager}
      />`;

    case "subtask":
      return html`<${SubtaskEventView}
        id=${id}
        depth=${depth}
        event=${event}
        stateManager=${stateManager}
      />`;

    case "tool":
      return html`<${ToolEventView}
        depth=${depth}
        id=${id}
        event=${event}
        stateManager=${stateManager}
      />`;

    default:
      return html``;
  }
};

/**
 * Normalizes event content
 *
 * @param {import("../../types/log").Events} events - The transcript events to display.
 * @returns {import("../../types/log").Events} Events with resolved content.
 */
const fixupEventStream = (events) => {
  const initEventIndex = events.findIndex((e) => {
    return e.event === "sample_init";
  });
  const initEvent = events[initEventIndex];

  const fixedUp = [...events];
  if (initEvent) {
    fixedUp.splice(initEventIndex, 0, {
      timestamp: initEvent.timestamp,
      event: "step",
      action: "begin",
      type: null,
      name: "sample_init",
    });

    fixedUp.splice(initEventIndex + 2, 0, {
      timestamp: initEvent.timestamp,
      event: "step",
      action: "end",
      type: null,
      name: "sample_init",
    });
  }

  return fixedUp;
};
