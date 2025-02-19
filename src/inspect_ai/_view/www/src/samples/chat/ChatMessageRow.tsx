import clsx from "clsx";
import { ChatMessage } from "./ChatMessage";

import styles from "./ChatMessageRow.module.css";
import { ResolvedMessage } from "./messages";

interface ChatMessageRowProps {
  parentName: string;
  number?: number;
  resolvedMessage: ResolvedMessage;
  toolCallStyle: "compact" | "complete";
  indented?: boolean;
}

/**
 * Renders the ChatMessage component.
 */
export const ChatMessageRow: React.FC<ChatMessageRowProps> = ({
  parentName,
  number,
  resolvedMessage,
  toolCallStyle,
  indented,
}) => {
  if (number) {
    return (
      <div className={styles.grid}>
        <div
          className={clsx(
            "text-size-smaller",
            "text-style-secondary",
            styles.number,
          )}
        >
          {number}
        </div>
        <ChatMessage
          id={`${parentName}-chat-messages`}
          message={resolvedMessage.message}
          toolMessages={resolvedMessage.toolMessages}
          indented={indented}
          toolCallStyle={toolCallStyle}
        />
      </div>
    );
  } else {
    return (
      <ChatMessage
        id={`${parentName}-chat-messages`}
        message={resolvedMessage.message}
        toolMessages={resolvedMessage.toolMessages}
        indented={indented}
        toolCallStyle={toolCallStyle}
      />
    );
  }
};
