import { RefObject } from "react";
import { VirtualList } from "../../components/VirtualList";
import { Messages } from "../../types/log";

import clsx from "clsx";
import { ChatMessageRow } from "./ChatMessageRow";
import styles from "./ChatViewVirtualList.module.css";
import { ResolvedMessage, resolveMessages } from "./messages";

interface ChatViewVirtualListProps {
  id?: string;
  messages: Messages;
  toolCallStyle: "compact" | "complete";
  className?: string | string[];
  indented: boolean;
  numbered?: boolean;
  scrollRef?: RefObject<HTMLElement | null>;
}

/**
 * Renders the ChatViewVirtualList component.
 */
export const ChatViewVirtualList: React.FC<ChatViewVirtualListProps> = ({
  id,
  messages,
  toolCallStyle,
  className,
  indented,
  numbered = true,
  scrollRef,
}) => {
  const collapsedMessages = resolveMessages(messages);

  const renderRow = (item: ResolvedMessage, index: number) => {
    const number =
      collapsedMessages.length > 1 && numbered ? index + 1 : undefined;
    return (
      <ChatMessageRow
        parentName={id || "chat-virtual-list"}
        number={number}
        resolvedMessage={item}
        indented={indented}
        toolCallStyle={toolCallStyle}
      />
    );
  };

  const result = (
    <VirtualList
      data={collapsedMessages}
      renderRow={renderRow}
      scrollRef={scrollRef}
      className={clsx(styles.list, className)}
    />
  );

  return result;
};
