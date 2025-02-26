import { FC, RefObject, useState } from "react";
import { Messages } from "../../types/log";

import clsx from "clsx";
import { Virtuoso } from "react-virtuoso";
import { ChatMessageRow } from "./ChatMessageRow";
import { ResolvedMessage, resolveMessages } from "./messages";

import styles from "./ChatViewVirtualList.module.css";

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
export const ChatViewVirtualList: FC<ChatViewVirtualListProps> = ({
  id,
  messages,
  toolCallStyle,
  className,
  indented,
  numbered = true,
  scrollRef,
}) => {
  const collapsedMessages = resolveMessages(messages);
  const [followOutput, setFollowOutput] = useState(false);

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
    <Virtuoso
      customScrollParent={scrollRef?.current ? scrollRef.current : undefined}
      style={{ height: "100%", width: "100%" }}
      data={collapsedMessages}
      itemContent={(index: number, data: ResolvedMessage) => {
        return renderRow(data, index);
      }}
      increaseViewportBy={{ top: 1000, bottom: 1000 }}
      overscan={{
        main: 10,
        reverse: 10,
      }}
      followOutput={followOutput}
      atBottomStateChange={(atBottom: boolean) => {
        setFollowOutput(atBottom);
      }}
      skipAnimationFrameInResizeObserver={true}
      className={clsx(styles.list, className)}
    />
  );

  return result;
};
