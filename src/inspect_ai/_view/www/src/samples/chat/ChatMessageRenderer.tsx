import { NavPills } from "../../components/NavPills.tsx";
import { Buckets, ContentRenderer } from "../../metadata/types.ts";
import {
  ChatMessageAssistant,
  ChatMessageSystem,
  ChatMessageTool,
  ChatMessageUser,
} from "../../types/log";
import { ChatView } from "./ChatView";

/**
 * Renders chat messages as a ChatView component.
 */
export const ChatMessageRenderer: ContentRenderer = {
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
      rendered: (
        <NavPills>
          <ChatSummary title="Last Turn" id={id} messages={entry.value} />
          <ChatView title="All" id={id} messages={entry.value} />
        </NavPills>
      ),
    };
  },
};

/**
 * Represents a chat summary component that renders a list of chat messages.
 */
export const ChatSummary: React.FC<{
  id: string;
  title?: string;
  messages: (
    | ChatMessageAssistant
    | ChatMessageUser
    | ChatMessageSystem
    | ChatMessageTool
  )[];
}> = ({ id, messages }) => {
  // Show the last 'turn'
  const summaryMessages = [];
  for (const message of messages.slice().reverse()) {
    summaryMessages.unshift(message);
    if (message.role === "user") {
      break;
    }
  }

  return <ChatView id={id} messages={summaryMessages} />;
};
