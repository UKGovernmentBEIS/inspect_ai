// @ts-check
import { html } from "htm/preact";
import { StateEventView } from "./StateEventView.mjs";
import { StepEventView } from "./StepEventView.mjs";
import { SubtaskEventView } from "./SubtaskEventView.mjs";
import { ModelEventView } from "./ModelEventView.mjs";
import { LoggerEventView } from "./LoggerEventView.mjs";
import { InfoEventView } from "./InfoEventView.mjs";

/**
 * Renders the TranscriptView component.
 *
 * @param {Object} params - The parameters for the component.
 * @param {import("../../types/log").Transcript} params.transcript - The transcript to display.
 * @returns {import("preact").JSX.Element} The TranscriptView component.
 */
export const TranscriptView = ({ transcript }) => {
  const rows = transcript.map((e, index) => {
    const rendered = getRenderer(e, index);
    return html`<div>${e.timestamp}</div>
      <div>${e.event}</div>
      <div>${rendered()}</div>`;
  });

  return html`<div
    style=${{
      fontSize: "0.8em",
      display: "grid",
      gridTemplateColumns: "auto auto auto",
      columnGap: "1em",
    }}
  >
    ${rows}
  </div>`;
};

/**
 * Fetches the renderer for the event
 *
 * @param {import("../../types/log").StateEvent | import("../../types/log").StoreEvent | import("../../types/log").ModelEvent | import("../../types/log").LoggerEvent | import("../../types/log").InfoEvent | import("../../types/log").StepEvent | import("../../types/log").SubtaskEvent} event - The event to fetch the renderer for
 * @param {number} index - The current event index
 * @returns {Function} - A function that returns the rendered event.
 */
const getRenderer = (event, index) => {
  switch (event.event) {
    case "info":
      return () => {
        return html`<${InfoEventView} index=${index} event=${event} />`;
      };

    case "logger":
      return () => {
        return html`<${LoggerEventView} index=${index} event=${event} />`;
      };

    case "model":
      return () => {
        return html`<${ModelEventView} index=${index} event=${event} />`;
      };

    case "state":
      return () => {
        return html`<${StateEventView} index=${index} event=${event} />`;
      };

    case "step":
      return () => {
        return html`<${StepEventView} index=${index} event=${event} />`;
      };

    case "store":
      return () => {
        return html`<${StateEventView} index=${index} event=${event} />`;
      };

    case "subtask":
      return () => {
        return html`<${SubtaskEventView} event=${event} />`;
      };
  }
};
