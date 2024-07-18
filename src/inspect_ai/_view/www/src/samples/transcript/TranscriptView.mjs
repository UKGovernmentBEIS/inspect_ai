// @ts-check
import { html } from "htm/preact";
import { StateEventView } from "./StateEventView.mjs";
import { StepEventViewStart } from "./StepEventViewStart.mjs";
import { SubtaskEventView } from "./SubtaskEventView.mjs";
import { ModelEventView } from "./ModelEventView.mjs";
import { LoggerEventView } from "./LoggerEventView.mjs";
import { InfoEventView } from "./InfoEventView.mjs";
import { StepEventViewEnd } from "./StepEventViewEnd.mjs";

/**
 * Renders the TranscriptView component.
 *
 * @param {Object} params - The parameters for the component.
 * @param {import("../../types/log").Transcript} params.transcript - The transcript to display.
 * @returns {import("preact").JSX.Element} The TranscriptView component.
 */
export const TranscriptView = ({ transcript }) => {
  const render = getRenderer();
  const rows = transcript.map((e, index) => {
    const rows = [
      html`
        <div style=${{ gridColumn: "1" }}>${e.timestamp}</div>
        <div
          style=${{
            gridColumn: "2",
            width: ".1em",
            borderRight: "solid var(--bs-light-border-subtle) .1em",
          }}
        ></div>
        <div style=${{ gridColumn: "3" }}>${render(e, index)}</div>
      `,
    ];

    const endStep = e.event === "step" && e.action === "end";
    if (endStep) {
      rows.push(
        html`<div
          style=${{
            gridColumn: "1/-1",
            borderTop: "solid var(--bs-light-border-subtle) .1em",
            height: ".1em",
            width: "100%",
            rowGap: "1em",
            paddingBottom: "1em",
          }}
        ></div>`,
      );
    }

    return rows;
  });

  return html`<div
    style=${{
      fontSize: "0.8em",
      display: "grid",
      gridTemplateColumns: "auto max-content auto",
      columnGap: "1em",
    }}
  >
    ${rows}
  </div>`;
};

/**
 * Fetches the renderer for the event
 *
 * @returns {Function} - A function that returns the rendered event.
 */
const getRenderer = () => {
  /**
   * @type {Date[]}
   */
  const stepStarts = [];

  /**
   * Renders the event based on its type.
   *
   * @param {import("../../types/log").StateEvent | import("../../types/log").StoreEvent | import("../../types/log").ModelEvent | import("../../types/log").LoggerEvent | import("../../types/log").InfoEvent | import("../../types/log").StepEvent | import("../../types/log").SubtaskEvent} event - The event to render.
   * @param {number} index - The current event index.
   * @returns {import("preact").JSX.Element} The rendered event.
   */
  return (event, index) => {
    switch (event.event) {
      case "info":
        return html`<${InfoEventView} index=${index} event=${event} />`;

      case "logger":
        return html`<${LoggerEventView} index=${index} event=${event} />`;

      case "model":
        return html`<${ModelEventView} index=${index} event=${event} />`;

      case "state":
        return html`<${StateEventView} index=${index} event=${event} />`;

      case "step":
        if (event.action === "begin") {
          stepStarts.push(new Date(event.timestamp));
          return html`<${StepEventViewStart} index=${index} event=${event} />`;
        } else {
          const stepStartTime = stepStarts.pop();
          return html`<${StepEventViewEnd}
            event=${event}
            stepStartTime=${stepStartTime}
          />`;
        }

      case "store":
        return html`<${StateEventView} index=${index} event=${event} />`;

      case "subtask":
        return html`<${SubtaskEventView} event=${event} />`;
    }
  };
};
