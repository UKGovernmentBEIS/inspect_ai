import { FC, memo, ReactNode, RefObject, useMemo } from "react";
import { Messages } from "../../../@types/log";

import { ChatMessageRow } from "./ChatMessageRow";
import { ResolvedMessage, resolveMessages } from "./messages";

import clsx from "clsx";
import { LiveVirtualList } from "../../../components/LiveVirtualList";
import { ChatViewToolCallStyle } from "./types";

import { ContextProp, ItemProps } from "react-virtuoso";
import styles from "./ChatViewVirtualList.module.css";

interface ChatViewVirtualListProps {
  id: string;
  className?: string | string[];
  messages: Messages;
  initialMessageId?: string | null;
  topOffset?: number;
  toolCallStyle: ChatViewToolCallStyle;
  indented: boolean;
  numbered?: boolean;
  scrollRef?: RefObject<HTMLDivElement | null>;
  running?: boolean;
  getMessageUrl?: (id: string) => string | undefined;
}

/**
 * Renders the ChatViewVirtualList component.
 */
export const ChatViewVirtualList: FC<ChatViewVirtualListProps> = memo(
  ({
    id,
    messages,
    initialMessageId,
    topOffset,
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
          highlightUserMessage={true}
        />
      );
    };

    const Item = ({
      children,
      ...props
    }: ItemProps<any> & ContextProp<any>) => {
      return (
        <div
          className={clsx(styles.item)}
          data-index={props["data-index"]}
          data-item-group-index={props["data-item-group-index"]}
          data-item-index={props["data-item-index"]}
          data-known-size={props["data-known-size"]}
          style={props.style}
        >
          {children}
        </div>
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
        offsetTop={topOffset}
        live={running}
        showProgress={running}
        components={{ Item }}
      />
    );
  },
);
