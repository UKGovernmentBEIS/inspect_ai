import { html } from "htm/preact";

import { Buckets } from "./Types.mjs";
import { ChatView } from "../ChatView.mjs";
import { NavPills } from "../NavPills.mjs";

/**
 * @type {import("./Types.mjs").ContentRenderer}
 *
 * Renders chat messages as a ChatView component.
 */
export const ChatMessageRenderer = {
  bucket: Buckets.first,
  canRender: (entry) => {
    const val = entry.value;
    return (
      Array.isArray(val) &&
      val.length > 0 &&
      val[0]?.role !== undefined &&
      val[0]?.content !== undefined
    );
  },
  render: (id, entry) => {
    return {
      rendered: html`
        <${NavPills}>
        <${ChatSummary} title="Last Turn" id=${id} messages=${entry.value} />
        <${ChatView} title="All" id=${id} messages=${entry.value} />
        </${NavPills}>
        `,
    };
  },
};

/**
 * Represents a chat summary component that renders a list of chat messages.
 *
 * @param {Object} props - The properties for the component.
 * @param {string} props.id - A unique identifier for the chat summary.
 * @param {(import("../../types/log").ChatMessageAssistant | import("../../types/log").ChatMessageUser | import("../../types/log").ChatMessageSystem | import("../../types/log").ChatMessageTool)[]} props.messages - A list of chat messages to display.
 * @returns {import("preact").JSX.Element} The rendered ChatView component.
 */
export const ChatSummary = ({ id, messages }) => {
  // Show the last 'turn'
  const summaryMessages = [];
  for (const message of messages.slice().reverse()) {
    summaryMessages.unshift(message);
    if (message.role === "user") {
      break;
    }
  }

  return html`<${ChatView} id=${id} messages=${summaryMessages} />`;
};
