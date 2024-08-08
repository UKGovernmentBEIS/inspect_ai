// @ts-check
import { html } from "htm/preact";
import { StateEventView } from "./StateEventView.mjs";
import { StepEventView } from "./StepEventView.mjs";
import { SubtaskEventView } from "./SubtaskEventView.mjs";
import { ModelEventView } from "./ModelEventView.mjs";
import { LoggerEventView } from "./LoggerEventView.mjs";
import { InfoEventView } from "./InfoEventView.mjs";
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
  // Resolve content Uris (content may be stored separately to avoid
  // repetition - it will be address with a uri)
  const resolvedEvents = resolveEventContent(evalEvents);

  // Resolve the events into a tree, with steps having children
  const eventNodes = resolveEventTree(resolvedEvents);

  const rows = eventNodes.map((node, index) => {
    const rows = [
      html`
        <div
          style=${{
            paddingTop: 0,
            paddingBottom: 0,
          }}
        >
          <div>${renderNode(`event${index}`, node)}</div>
        </div>
      `,
    ];

    return rows;
  });

  return html`<div
    style=${{
      fontSize: "0.8em",
      display: "grid",
      marginTop: "1em",
    }}
  >
    ${rows}
  </div>`;
};

/**
 * Renders the event based on its type.
 *
 * @param {EventNode} node
 * @param {string} id - The id for this event.
 * @returns {import("preact").JSX.Element} The rendered event.
 */
export const renderNode = (id, node) => {
  switch (node.event.event) {
    case "info":
      return html`<${InfoEventView} id=${id} event=${node.event} />`;

    case "logger":
      return html`<${LoggerEventView} id=${id} event=${node.event} />`;

    case "model":
      return html`<${ModelEventView} id=${id} event=${node.event} />`;

    case "score":
      return html`<${ScoreEventView} id=${id} event=${node.event} />`;

    case "state":
      return html`<${StateEventView} id=${id} event=${node.event} />`;

    case "step":
      return html`<${StepEventView}
        id=${id}
        event=${node.event}
        children=${node.children}
      />`;

    case "store":
      return html`<${StateEventView} id=${id} event=${node.event} />`;

    case "subtask":
      return html`<${SubtaskEventView} id=${id} event=${node.event} />`;

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
  } else if (value && typeof value === "object") {
    const resolvedObject = {};
    for (const key in Object.keys(value)) {
      resolvedObject[key] = resolveValue(value[key], evalEvents);
    }
    return resolvedObject;
  } else if (typeof value === "string") {
    if (value.startsWith(kContentProtocol)) {
      value = evalEvents.content[value.replace(kContentProtocol, "")];
    }
  }
  return value;
};

/**
 * @typedef {Object} EventNode
 * @param {import("../../types/log").StateEvent | import("../../types/log").StoreEvent | import("../../types/log").ModelEvent | import("../../types/log").LoggerEvent | import("../../types/log").InfoEvent | import("../../types/log").StepEvent | import("../../types/log").SubtaskEvent| import("../../types/log").ScoreEvent} event - This event
 * @property {import("../../types/log").StateEvent} children - child events
 */

/**
 * Resolves Events into a tree of nodes with children
 *
 * @param {import("../../types/log").Events} events - The transcript events to display.
 * @returns {EventNode[]} Nodes containing events and children.
 */
const resolveEventTree = (events) => {
  const rootNodes = [];
  let currentNode = null;
  const stack = [];

  events.forEach((event) => {
    if (event.event === "step" && event.action === "begin") {
      const newNode = { event, children: [] };
      if (currentNode) {
        currentNode.children.push(newNode);
        stack.push(currentNode);
      } else {
        rootNodes.push(newNode);
      }
      currentNode = newNode;
    } else if (event.event === "step" && event.action === "end") {
      if (stack.length > 0) {
        currentNode = stack.pop();
      } else {
        currentNode = null;
      }
    } else {
      const newNode = { event, children: [] };
      if (currentNode) {
        currentNode.children.push(newNode);
      } else {
        rootNodes.push(newNode);
      }
    }
  });
  return rootNodes;
};
