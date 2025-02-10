import clsx from "clsx";
import { Fragment } from "react";
import ExpandablePanel from "../../components/ExpandablePanel";
import { MarkdownDiv } from "../../components/MarkdownDiv";
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

export const ChatMessage: React.FC<ChatMessageProps> = ({
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
      {message.role === "assistant" && message.reasoning ? (
        <Fragment key={`${id}-response-label`}>
          <div className={clsx("text-style-label", "text-style-secondary")}>
            Reasoning
          </div>
          <ExpandablePanel collapse={true}>
            <MarkdownDiv markdown={message.reasoning} />
          </ExpandablePanel>
        </Fragment>
      ) : undefined}
      <div
        className={clsx(
          styles.messageContents,
          indented ? styles.indented : undefined,
        )}
      >
        {message.role === "assistant" && message.reasoning ? (
          <div className={clsx("text-style-label", "text-style-secondary")}>
            Response
          </div>
        ) : undefined}
        <ExpandablePanel collapse={collapse}>
          <MessageContents
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
