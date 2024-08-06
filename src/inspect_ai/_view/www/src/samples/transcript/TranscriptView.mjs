// @ts-check
import { html } from "htm/preact";
import { StateEventView } from "./StateEventView.mjs";
import { StepEventViewStart } from "./StepEventViewStart.mjs";
import { SubtaskEventView } from "./SubtaskEventView.mjs";
import { ModelEventView } from "./ModelEventView.mjs";
import { LoggerEventView } from "./LoggerEventView.mjs";
import { InfoEventView } from "./InfoEventView.mjs";
import { StepEventViewEnd } from "./StepEventViewEnd.mjs";
import { ScoreEventView } from "./ScoreEventView.mjs";

const kContentProtocol = "tc://";

/**
 * Renders the TranscriptView component.
 *
 * @param {Object} params - The parameters for the component.
 * @param {import("../../types/log").EvalEvents} params.evalEvents - The transcript events to display.
 * @returns {import("preact").JSX.Element} The TranscriptView component.
 */
export const TranscriptView = ({ evalEvents }) => {
  let stepDepth = 0;
  const render = getRenderer();
  const rows = resolveEventContent(evalEvents).map((e, index) => {
    const endStep = e.event === "step" && e.action === "end";
    if (endStep) {
      stepDepth--;
    }

    const indentStyle = {};
    const indentDepth = stepDepth * 1.5;
    if (indentDepth > 0) {
      indentStyle["marginLeft"] = `${indentDepth}em`;
    }

    const beginStep = e.event === "step" && e.action === "begin";
    if (beginStep) {
      stepDepth++;
    }

    const rows = [
      html`
        <div
          style=${{
            paddingTop: ".4em",
            paddingBottom: ".4em",
          }}
        >
          <div style=${indentStyle}>${render(e, index)}</div>
        </div>
      `,
    ];

    if (endStep && stepDepth === 0) {
      rows.push(
        html`<div
          style=${{
            borderTop: "solid var(--bs-light-border-subtle) .1em",
            height: ".1em",
            width: "100%",
            rowGap: "1em",
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
   * @param {import("../../types/log").StateEvent | import("../../types/log").StoreEvent | import("../../types/log").ModelEvent | import("../../types/log").LoggerEvent | import("../../types/log").InfoEvent | import("../../types/log").StepEvent | import("../../types/log").SubtaskEvent| import("../../types/log").ScoreEvent} event - The event to render.
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

      case "score":
        return html`<${ScoreEventView} index=${index} event=${event} />`;

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

/**
 * Resolves event content
 *
 * @param {import("../../types/log").EvalEvents} evalEvents - The transcript events to display.
 * @returns {import("../../types/log").Events} Events with resolved content.
 */
const resolveEventContent = (evalEvents) => {
  return evalEvents.events.map((e) => {
    if (e.event === "model") {
      // @ts-ignore
      e.input = resolveValue(e.input, evalEvents);
      // @ts-ignore
      e.output = resolveValue(e.output, evalEvents);
      return e;
    } else if (e.event === "state") {
      e.changes = e.changes.map((change) => {
        change.value = resolveValue(change.value, evalEvents);
        return change;
      });
      return e;
    }
    return e;
  });
};

/**
 * Resolves individual value
 *
 * @param {unknown} value - The value to resolve
 * @param {import("../../types/log").EvalEvents} evalEvents - The transcript events to display.
 * @returns {unknown} Value with resolved content.
 */
const resolveValue = (value, evalEvents) => {
  if (Array.isArray(value)) {
    return value.map((v) => {
      return resolveValue(v, evalEvents);
    });
  } else if (typeof value === "object") {
    const resolvedObject = {};
    for (const key in value) {
      if (value.hasOwnProperty(key)) {
        resolvedObject[key] = resolveValue(value[key], evalEvents);
      }
    }
    return resolvedObject;
  } else if (typeof value === "string") {
    if (value.startsWith(kContentProtocol)) {
      value = evalEvents.content[value.replace(kContentProtocol, "")];
    }
  }
  return value;
};
