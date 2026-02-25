import clsx from "clsx";
import { FC, memo, useState } from "react";
import { ChatMessageTool } from "../../../@types/log";
import { CopyButton } from "../../../components/CopyButton";
import ExpandablePanel from "../../../components/ExpandablePanel";
import { LabeledValue } from "../../../components/LabeledValue";
import { formatDateTime } from "../../../utils/format";
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
import { Message } from "./messages";

interface ChatMessageProps {
  id: string;
  message: Message;
  toolMessages: ChatMessageTool[];
  indented?: boolean;
  toolCallStyle: ChatViewToolCallStyle;
  allowLinking?: boolean;
  hideRoleForRoles?: string[];
}

export const ChatMessage: FC<ChatMessageProps> = memo(
  ({
    id,
    message,
    toolMessages,
    indented,
    toolCallStyle,
    allowLinking = true,
    hideRoleForRoles,
  }) => {
    const messageUrl = useSampleMessageUrl(message.id);

    const collapse = message.role === "system" || message.role === "user";
    const hideRole = hideRoleForRoles?.includes(message.role) ?? false;

    // When the role header is hidden, skip rendering if there's no visible
    // text content (e.g. assistant messages with only tool_calls).
    if (hideRole) {
      const content = message.content;
      const hasVisibleContent =
        typeof content === "string"
          ? content.trim().length > 0
          : Array.isArray(content) &&
            content.some((c) => c.type !== "tool_use");
      if (!hasVisibleContent) {
        return null;
      }
    }

    const [mouseOver, setMouseOver] = useState(false);

    return (
      <div
        className={clsx(
          message.role,
          "text-size-base",
          styles.message,
          message.role === "system" ? styles.systemRole : undefined,
          message.role === "user" ? styles.userRole : undefined,
          mouseOver ? styles.hover : undefined,
        )}
        onMouseEnter={() => setMouseOver(true)}
        onMouseLeave={() => setMouseOver(false)}
      >
        {!hideRole && (
          <div
            className={clsx(
              styles.messageGrid,
              message.role === "tool" ? styles.toolMessageGrid : undefined,
              "text-style-label",
            )}
          >
            <div>
              {message.role}
              {message.role === "tool" ? `: ${message.function}` : ""}
              {supportsLinking() && messageUrl && allowLinking ? (
                <CopyButton
                  icon={ApplicationIcons.link}
                  value={toFullUrl(messageUrl)}
                  className={clsx(styles.copyLink)}
                />
              ) : (
                ""
              )}
            </div>
            {message.timestamp && (
              <span className={styles.timestamp} title={message.timestamp}>
                {formatDateTime(new Date(message.timestamp))}
              </span>
            )}
          </div>
        )}
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
                defaultExpandLevel={0}
              />
            </LabeledValue>
          ) : (
            ""
          )}
        </div>
      </div>
    );
  },
);
