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
import { LabeledValue } from "../../../components/LabeledValue";
import { ApplicationIcons } from "../../appearance/icons";
import { RecordTree } from "../../content/RecordTree";
import {
  supportsLinking,
  toFullUrl,
  useSampleMessageUrl,
} from "../../routing/url";
import styles from "./ChatMessage.module.css";
import { MessageContents } from "./MessageContents";
import { ChatViewToolCallStyle } from "./types";

interface ChatMessageProps {
  id: string;
  message: ChatMessageAssistant | ChatMessageSystem | ChatMessageUser;
  toolMessages: ChatMessageTool[];
  indented?: boolean;
  toolCallStyle: ChatViewToolCallStyle;
}

export const ChatMessage: FC<ChatMessageProps> = ({
  id,
  message,
  toolMessages,
  indented,
  toolCallStyle,
}) => {
  const messageUrl = useSampleMessageUrl(message.id);

  const collapse = message.role === "system" || message.role === "user";
  return (
    <div
      className={clsx(
        message.role,
        "text-size-base",
        styles.message,
        message.role === "system" ? styles.systemRole : undefined,
        message.role === "user" ? styles.userRole : undefined,
      )}
    >
      <div className={clsx(styles.messageGrid, "text-style-label")}>
        {message.role}
        {supportsLinking() && messageUrl ? (
          <CopyButton
            icon={ApplicationIcons.link}
            value={toFullUrl(messageUrl)}
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

        {message.metadata && Object.keys(message.metadata).length > 0 ? (
          <LabeledValue
            label="Metadata"
            className={clsx(styles.metadataLabel, "text-size-smaller")}
          >
            <RecordTree
              record={message.metadata}
              id={`${id}-metadata`}
              defaultExpandLevel={1}
            />
          </LabeledValue>
        ) : (
          ""
        )}
      </div>
    </div>
  );
};
