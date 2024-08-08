// @ts-check
import { html } from "htm/preact";
import { ChatView } from "../../../components/ChatView.mjs";

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
  type: "tools_choice",
  signature: {
    add: ["/tools/0"],
    replace: ["/tool_choice"],
    remove: [],
  },
  render: (resolvedState) => {
    return html`Tool Choice: ${resolvedState.tool_choice}`;
  },
};

/** @type {ChangeType[]} */
export const RenderableChangeTypes = [system_msg_added_sig, tools_choice];
