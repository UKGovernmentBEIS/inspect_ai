import clsx from "clsx";
import { FC } from "react";
import ExpandablePanel from "../../components/ExpandablePanel";
import {
  ChatMessageAssistant,
  ChatMessageSystem,
  ChatMessageTool,
  ChatMessageUser,
} from "../../types/log";
import styles from "./ChatMessage.module.css";
import { MessageContents } from "./MessageContents";
import { iconForMsg } from "./messages";

interface ChatMessageProps {
  id: string;
  message: ChatMessageAssistant | ChatMessageSystem | ChatMessageUser;
  toolMessages: ChatMessageTool[];
  indented?: boolean;
  toolCallStyle: "compact" | "complete";
}

export const ChatMessage: FC<ChatMessageProps> = ({
  id,
  message,
  toolMessages,
  indented,
  toolCallStyle,
}) => {
  const collapse = message.role === "system";
  return (
    <div
      className={clsx(
        message.role,
        "text-size-base",
        styles.message,
        message.role === "system" ? styles.systemRole : undefined,
      )}
    >
      <div className={clsx(styles.messageGrid, "text-style-label")}>
        <i className={iconForMsg(message)} />
        {message.role}
      </div>
      <div
        className={clsx(
          styles.messageContents,
          indented ? styles.indented : undefined,
        )}
      >
        <ExpandablePanel id={`${id}-message`} collapse={collapse} lines={30}>
          <MessageContents
            id={`${id}-contents`}
            key={`${id}-contents`}
            message={message}
            toolMessages={toolMessages}
            toolCallStyle={toolCallStyle}
          />
        </ExpandablePanel>
      </div>
    </div>
  );
};
