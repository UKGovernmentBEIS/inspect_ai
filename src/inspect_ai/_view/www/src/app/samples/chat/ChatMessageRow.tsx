import clsx from "clsx";
import { ChatMessage } from "./ChatMessage";

import { FC } from "react";
import styles from "./ChatMessageRow.module.css";
import { ResolvedMessage } from "./messages";
import { ChatViewToolCallStyle } from "./types";

interface ChatMessageRowProps {
  parentName: string;
  number?: number;
  resolvedMessage: ResolvedMessage;
  toolCallStyle: ChatViewToolCallStyle;
  indented?: boolean;
  padded?: boolean;
}

/**
 * Renders the ChatMessage component.
 */
export const ChatMessageRow: FC<ChatMessageRowProps> = ({
  parentName,
  number,
  resolvedMessage,
  toolCallStyle,
  indented,
  padded,
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
          padded={padded}
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
        padded={padded}
      />
    );
  }
};
