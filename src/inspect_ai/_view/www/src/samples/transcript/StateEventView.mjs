// @ts-check
import { html } from "htm/preact";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { EventPanel } from "./EventPanel.mjs";
import { applyOperation } from "fast-json-patch";
import { ChatView } from "../../components/ChatView.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param {import("../../types/log").StateEvent | import("../../types/log").StoreEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const StateEventView = ({ id, event }) => {
  const resolvedState = {
    messages: [
      {
        source: undefined,
        role: "user",
        content: "sample input",
      },
    ],
    metadata: {},
    tools: [],
    output: {
      choices: [],
    },
  };
  event.changes.forEach((change) => {
    //@ts-ignore
    applyOperation(resolvedState, change);
  });

  const tabs = [html`<${ChangeDiffPanel} changes=${event.changes} />`];
  const changePreview = generatePreview(event.changes, resolvedState);
  if (changePreview) {
    tabs.unshift(changePreview);
  }

  // Compute the title
  const title = event.event === "state" ? "State Updated" : "Store Updated";
  return html`
  <${EventPanel} id=${id} title=${title}>
    ${tabs}
  </${EventPanel}>`;
};

/**
 * Returns a symbol representing the operation type.
 *
 * @param {string} op - The operation type.
 * @returns {import("preact").JSX.Element | undefined} The component.
 */
const iconForOp = (op) => {
  switch (op) {
    case "add":
      return html`<i class="${ApplicationIcons.changes.add}" />`;
    case "remove":
      return html`<i class="${ApplicationIcons.changes.remove}" />`;
    case "replace":
      return html`<i class="${ApplicationIcons.changes.replace}" />`;
    case "copy":
    case "move":
    case "test":
    default:
      return undefined;
  }
};

/**
 * Returns a background color configuration based on the operation type.
 *
 * @param {string} op - The operation type.
 * @returns {string|undefined} - The color configuration, or undefined for certain operations.
 */
const colorForOp = (op) => {
  switch (op) {
    case "add":
      return "var(--bs-success)";
    case "remove":
      return "var(--bs-danger)";
    case "replace":
      return "var(--bs-success)";
    case "copy":
    case "move":
    case "test":
    default:
      return undefined;
  }
};

/**
 * Renders the value of a change based on its type.
 *
 * @param {import("../../types/log").JsonChange} change - The change object containing the value.
 * @returns {import("preact").JSX.Element|Object|string} - The rendered HTML template if the value is an object with content and source, otherwise the value itself.
 */
const renderValue = (change) => {
  const contents =
    typeof change.value === "object" || Array.isArray(change.value)
      ? JSON.stringify(change.value, null, 2)
      : typeof change.value === "string"
        ? change.value.trim()
        : change.value;

  return html`<pre
    style=${{
      whiteSpace: "pre-wrap",
      wordBreak: "break-word",
      marginBottom: "0",
    }}
  >
${contents || ""}</pre
  >`;
};

/**
 * @typedef {Object} Signature
 * @property {string[]} remove - Array of paths to be removed.
 * @property {string[]} replace - Array of paths to be replaced.
 * @property {string[]} add - Array of paths to be added.
 */

/**
 * @typedef {Object} ChangeType
 * @property {string} type - Type of the system message.
 * @property {Signature} signature - Signature of the system message.
 * @property {function(Object): import("preact").JSX.Element} render - Function to render the resolved state.
 */

/** @type {ChangeType} */
const system_msg_added_sig = {
  type: "system_message",
  signature: {
    remove: ["/messages/0/source"],
    replace: ["/messages/0/role", "/messages/0/content"],
    add: ["/messages/1"],
  },
  render: (resolvedState) => {
    const message = resolvedState["messages"][0];
    return html`<${ChatView}
      id="system_msg_event_preview"
      messages=${[message]}
    />`;
  },
};

/** @type {ChangeType} */
const tools_choice = {
  type:"tools_choice",
  signature: {
    add: ["/tools/0"],
    replace: ["/tool_choice"],
    remove: []
  },
  render: (resolvedState) => {
    return html`Tool Choice: ${resolvedState.tool_choice}`;
  }
}

/** @type {ChangeType[]} */
const changeTypes = [system_msg_added_sig, tools_choice];

/**
 * Renders the value of a change based on its type.
 *
 * @param {import("../../types/log").JsonChange[]} changes - The change object containing the value.
 * @returns {import("preact").JSX.Element|Object|string} - The rendered HTML template if the value is an object with content and source, otherwise the value itself.
 */
const generatePreview = (changes, resolvedState) => {
  for (const changeType of changeTypes) {
    const requiredMatchCount =
      changeType.signature.remove.length +
      changeType.signature.replace.length +
      changeType.signature.add.length;
    let matchingOps = 0;
    for (const change of changes) {
      if (
        changeType.signature.remove.includes(change.path) ||
        changeType.signature.replace.includes(change.path) ||
        changeType.signature.add.includes(change.path)
      ) {
        matchingOps++;
      }
      if (matchingOps === requiredMatchCount) {
        return changeType.render(resolvedState);
      }
    }
  }
  return undefined;
};

const ChangeDiffPanel = ({ changes }) => {
  const mutations = changes.map((change) => {
    // Compute the change rows
    const symbol = iconForOp(change.op);
    const color = colorForOp(change.op);
    const toStyle = {};
    const baseStyle = {
      color,
    };
    return html`
      <div style=${baseStyle}>${symbol ? symbol : ""}</div>
      <code style=${{ padding: "0", ...baseStyle }}>${change.path}</code>
      <div style=${toStyle}>${renderValue(change)}</div>
    `;
  });

  return html`<div
    style=${{
      display: "grid",
      gridTemplateColumns: "max-content max-content 1fr",
      columnGap: "1em",
      rowGap: 0,
    }}
  >
    ${mutations}
  </div>`;
};
