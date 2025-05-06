import clsx from "clsx";
import { FC } from "react";
import {
  ChatMessageAssistant,
  ChatMessageSystem,
  ChatMessageTool,
  ChatMessageUser,
} from "../../../@types/log";
import { CopyButton } from "../../../components/CopyButton";
import ExpandablePanel from "../../../components/ExpandablePanel";
import { ApplicationIcons } from "../../appearance/icons";
import styles from "./ChatMessage.module.css";
import { MessageContents } from "./MessageContents";
import { iconForMsg } from "./messages";
import { ChatViewToolCallStyle } from "./types";

interface ChatMessageProps {
  id: string;
  message: ChatMessageAssistant | ChatMessageSystem | ChatMessageUser;
  toolMessages: ChatMessageTool[];
  indented?: boolean;
  toolCallStyle: ChatViewToolCallStyle;
  padded?: boolean;
  getMessageUrl?: (id: string) => string | undefined;
}

export const ChatMessage: FC<ChatMessageProps> = ({
  id,
  message,
  toolMessages,
  indented,
  toolCallStyle,
  padded,
  getMessageUrl,
}) => {
  const messageUrl =
    message.id && getMessageUrl ? getMessageUrl(message.id) : undefined;

  const collapse = message.role === "system" || message.role === "user";
  return (
    <div
      className={clsx(
        message.role,
        "text-size-base",
        styles.message,
        padded ? styles.padded : undefined,
        message.role === "system" ? styles.systemRole : undefined,
      )}
    >
      <div className={clsx(styles.messageGrid, "text-style-label")}>
        <i className={iconForMsg(message)} />
        {message.role}
        {messageUrl ? (
          <CopyButton
            icon={ApplicationIcons.link}
            value={messageUrl}
            className={clsx(styles.copyLink)}
          />
        ) : (
          ""
        )}
      </div>
      <div
        className={clsx(
          styles.messageContents,
          indented ? styles.indented : undefined,
        )}
      >
        <ExpandablePanel
          id={`${id}-message`}
          collapse={collapse}
          lines={collapse ? 15 : 25}
        >
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
