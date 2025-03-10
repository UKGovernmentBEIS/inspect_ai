import { FC, RefObject, useRef } from "react";
import { Messages } from "../../types/log";

import clsx from "clsx";
import { Virtuoso, VirtuosoHandle } from "react-virtuoso";
import { ChatMessageRow } from "./ChatMessageRow";
import { ResolvedMessage, resolveMessages } from "./messages";

import { useProperty } from "../../state/hooks";
import { useVirtuosoState } from "../../state/scrolling";
import styles from "./ChatViewVirtualList.module.css";

interface ChatViewVirtualListProps {
  id: string;
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

  const [followOutput, setFollowOutput] = useProperty(id, "follow", {
    defaultValue: false,
  });

  const listHandle = useRef<VirtuosoHandle>(null);
  const { restoreState, isScrolling } = useVirtuosoState(
    listHandle,
    `chat-view-${id}`,
  );

  const renderRow = (index: number, item: ResolvedMessage) => {
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
      ref={listHandle}
      customScrollParent={scrollRef?.current ? scrollRef.current : undefined}
      style={{ height: "100%", width: "100%" }}
      data={collapsedMessages}
      itemContent={renderRow}
      increaseViewportBy={{ top: 1000, bottom: 1000 }}
      overscan={{
        main: 10,
        reverse: 10,
      }}
      followOutput={followOutput}
      atBottomStateChange={setFollowOutput}
      skipAnimationFrameInResizeObserver={true}
      className={clsx(styles.list, className)}
      restoreStateFrom={restoreState}
      isScrolling={isScrolling}
    />
  );

  return result;
};
