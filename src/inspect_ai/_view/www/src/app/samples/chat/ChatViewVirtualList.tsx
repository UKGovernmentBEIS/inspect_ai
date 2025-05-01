import { FC, memo, ReactNode, RefObject, useMemo } from "react";
import { Messages } from "../../../@types/log";

import { ChatMessageRow } from "./ChatMessageRow";
import { ResolvedMessage, resolveMessages } from "./messages";

import { LiveVirtualList } from "../../../components/LiveVirtualList";
import { ChatViewToolCallStyle } from "./types";

interface ChatViewVirtualListProps {
  id: string;
  className?: string | string[];
  messages: Messages;
  initialMessageId?: string | null;
  toolCallStyle: ChatViewToolCallStyle;
  indented: boolean;
  numbered?: boolean;
  scrollRef?: RefObject<HTMLDivElement | null>;
  running?: boolean;
}

/**
 * Renders the ChatViewVirtualList component.
 */
export const ChatViewVirtualList: FC<ChatViewVirtualListProps> = memo(
  ({
    id,
    messages,
    initialMessageId,
    className,
    toolCallStyle,
    indented,
    numbered = true,
    scrollRef,
    running,
  }) => {
    const collapsedMessages = useMemo(() => {
      return resolveMessages(messages);
    }, [messages]);

    const initialMessageIndex = useMemo(() => {
      if (initialMessageId === null || initialMessageId === undefined) {
        return undefined;
      }

      const index = collapsedMessages.findIndex((message) => {
        return message.message.id === initialMessageId;
      });
      return index !== -1 ? index : undefined;
    }, [initialMessageId, collapsedMessages]);

    const renderRow = (index: number, item: ResolvedMessage): ReactNode => {
      const number =
        collapsedMessages.length > 1 && numbered ? index + 1 : undefined;

      return (
        <ChatMessageRow
          parentName={id || "chat-virtual-list"}
          number={number}
          resolvedMessage={item}
          indented={indented}
          toolCallStyle={toolCallStyle}
          padded={index < collapsedMessages.length - 1}
        />
      );
    };

    return (
      <LiveVirtualList<ResolvedMessage>
        id="chat-virtual-list"
        className={className}
        scrollRef={scrollRef}
        data={collapsedMessages}
        renderRow={renderRow}
        initialTopMostItemIndex={initialMessageIndex}
        live={running}
        showProgress={running}
      />
    );
  },
);
