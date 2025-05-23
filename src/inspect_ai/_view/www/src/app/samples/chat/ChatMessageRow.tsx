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
  highlightUserMessage?: boolean;
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
  highlightUserMessage,
}) => {
  if (number) {
    return (
      <>
        <div
          className={clsx(
            styles.grid,
            styles.container,
            highlightUserMessage && resolvedMessage.message.role === "user"
              ? styles.user
              : undefined,
          )}
        >
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

        {resolvedMessage.message.role === "user" ? (
          <div style={{ height: "10px" }}></div>
        ) : undefined}
      </>
    );
  } else {
    return (
      <div
        className={clsx(
          styles.container,
          styles.simple,
          highlightUserMessage && resolvedMessage.message.role === "user"
            ? styles.user
            : undefined,
        )}
      >
        <ChatMessage
          id={`${parentName}-chat-messages`}
          message={resolvedMessage.message}
          toolMessages={resolvedMessage.toolMessages}
          indented={indented}
          toolCallStyle={toolCallStyle}
        />
        {resolvedMessage.message.role === "user" ? (
          <div style={{ height: "10px" }}></div>
        ) : undefined}
      </div>
    );
  }
};
