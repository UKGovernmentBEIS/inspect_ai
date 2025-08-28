import clsx from "clsx";
import { FC } from "react";
import { Messages } from "../../../@types/log";
import { ChatMessageRow } from "./ChatMessageRow";
import { resolveMessages } from "./messages";
import { ChatViewToolCallStyle } from "./types";

interface ChatViewProps {
  id?: string;
  messages: Messages;
  toolCallStyle?: ChatViewToolCallStyle;
  resolveToolCallsIntoPreviousMessage?: boolean;
  title?: string;
  indented?: boolean;
  numbered?: boolean;
  className?: string | string[];
}

/**
 * Renders the ChatView component.
 */
export const ChatView: FC<ChatViewProps> = ({
  id,
  messages,
  toolCallStyle = "complete",
  resolveToolCallsIntoPreviousMessage = true,
  indented,
  numbered = true,
  className,
}) => {
  const collapsedMessages = resolveToolCallsIntoPreviousMessage
    ? resolveMessages(messages)
    : messages.map((msg) => {
        return {
          message: msg,
          toolMessages: [],
        };
      });
  const result = (
    <div className={clsx(className)}>
      {collapsedMessages.map((msg, index) => {
        const number =
          collapsedMessages.length > 1 && numbered ? index + 1 : undefined;
        return (
          <ChatMessageRow
            key={`${id}-msg-${index}`}
            parentName={id || "chat-view"}
            number={number}
            resolvedMessage={msg}
            indented={indented}
            toolCallStyle={toolCallStyle}
          />
        );
      })}
    </div>
  );
  return result;
};
