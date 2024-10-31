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
import { ErrorEventView } from "./ErrorEventView.mjs";
import { InputEventView } from "./InputEventView.mjs";
import { ApprovalEventView } from "./ApprovalEventView.mjs";
import { FontSize } from "../../appearance/Fonts.mjs";
import { EventNode } from "./Types.mjs";

/**
 * Renders the TranscriptView component.
 *
 * @param {Object} props - The parameters for the component.
 * @param {string} props.id - The identifier for this view
 * @param {import("../../types/log").Events} props.events - The transcript events to display.
 * @param {number} props.depth - The base depth for this transcript view
 * @returns {import("preact").JSX.Element} The TranscriptView component.
 */
export const TranscriptView = ({ id, events, depth = 0 }) => {
  // Normalize Events themselves
  const resolvedEvents = fixupEventStream(events);
  const eventNodes = treeifyEvents(resolvedEvents, depth);
  return html` <${TranscriptComponent} id=${id} eventNodes=${eventNodes} /> `;
};

/**
 * Renders the Transcript component.
 *
 * @param {Object} props - The parameters for the component.
 * @param {string} props.id - The identifier for this view
 * @param {EventNode[]} props.eventNodes - The transcript events nodes to display.
 * @param {Object} props.style - The transcript style to display.
 * @returns {import("preact").JSX.Element} The TranscriptView component.
 */
export const TranscriptComponent = ({ id, eventNodes, style }) => {
  const rows = eventNodes.map((eventNode, index) => {
    const toggleStyle = {};
    if (eventNode.depth % 2 == 0) {
      toggleStyle.backgroundColor = "var(--bs-light-bg-subtle)";
    } else {
      toggleStyle.backgroundColor = "var(--bs-body-bg)";
    }
    if (index === eventNodes.length - 1) {
      toggleStyle.marginBottom = "0";
    } else if (eventNode.depth === 0) {
      toggleStyle.marginBottom = "1.5em";
    }

    const row = html`
      <${RenderedEventNode}
        id=${`${id}-event${index}`}
        node=${eventNode}
        style=${{
          ...toggleStyle,
          ...style,
        }}
      />
    `;
    return row;
  });

  return html`<div
    id=${id}
    key=${id}
    style=${{
      fontSize: FontSize.small,
      display: "grid",
      margin: "0.5em 0 0 0",
      width: "100%",
    }}
  >
    ${rows}
  </div>`;
};

/**
 * Renders the event based on its type.
 *
 * @param { Object } props - This event.
 * @param {string} props.id - The id for this event.
 * @param { EventNode } props.node - This event.
 * @param { Object } props.style - The style for this node.
 * @returns {import("preact").JSX.Element} The rendered event.
 */
export const RenderedEventNode = ({ id, node, style }) => {
  switch (node.event.event) {
    case "sample_init":
      return html`<${SampleInitEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;

    case "info":
      return html`<${InfoEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;

    case "logger":
      return html`<${LoggerEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;

    case "model":
      return html`<${ModelEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;

    case "score":
      return html`<${ScoreEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;

    case "state":
      return html`<${StateEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;

    case "step":
      return html`<${StepEventView}
        id=${id}
        event=${node.event}
        children=${node.children}
        style=${style}
      />`;

    case "store":
      return html`<${StateEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;

    case "subtask":
      return html`<${SubtaskEventView}
        id=${id}
        event=${node.event}
        style=${style}
        depth=${node.depth}
      />`;

    case "tool":
      return html`<${ToolEventView}
        id=${id}
        event=${node.event}
        style=${style}
        depth=${node.depth}
      />`;

    case "input":
      return html`<${InputEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;

    case "error":
      return html`<${ErrorEventView}
        id=${id}
        event=${node.event}
        style=${style}
      />`;

    case "approval":
      return html`<${ApprovalEventView}
        id=${id}
        event=${node.event}
        style=${style}
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

/**
 * Gathers events into a hierarchy of EventNodes.
 * @param {import("../../types/log").Events} events - The transcript events to display.
 * @param { number } depth - the base depth
 * @returns {EventNode[]} An array of root EventNodes.
 */
function treeifyEvents(events, depth) {
  const rootNodes = [];
  const stack = [];

  const pushNode = (event) => {
    const node = new EventNode(event, stack.length + depth);
    if (stack.length > 0) {
      const parentNode = stack[stack.length - 1];
      parentNode.children.push(node);
    } else {
      rootNodes.push(node);
    }
    return node;
  };

  events.forEach((event) => {
    if (event.event === "step" && event.action === "begin") {
      // Starting a new step
      const node = pushNode(event);
      stack.push(node);
    } else if (event.event === "step" && event.action === "end") {
      // An ending step
      if (stack.length > 0) {
        stack.pop();
      }
    } else {
      // An event
      pushNode(event);
    }
  });

  return rootNodes;
}
