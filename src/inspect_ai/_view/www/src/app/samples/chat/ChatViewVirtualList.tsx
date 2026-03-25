import {
  FC,
  memo,
  ReactNode,
  RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
} from "react";
import { Messages } from "../../../@types/log";

import { ChatMessageRow } from "./ChatMessageRow";
import { ResolvedMessage, resolveMessages } from "./messages";

import clsx from "clsx";
import { LiveVirtualList } from "../../../components/LiveVirtualList";
import { ChatViewToolCallStyle } from "./types";

import { ContextProp, ItemProps, VirtuosoHandle } from "react-virtuoso";
import { useStore } from "../../../state/store";
import { ChatView } from "./ChatView";
import styles from "./ChatViewVirtualList.module.css";
import { messageSearchText } from "./messageSearchText";

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
  allowLinking?: boolean;
}

interface ChatViewVirtualListComponentProps extends ChatViewVirtualListProps {
  listHandle: RefObject<VirtuosoHandle | null>;
}

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
    allowLinking = true,
  }) => {
    // Support either virtualized or normal mode rendering based upon message count
    const useVirtuoso = running || messages.length > 200;
    const listHandle = useRef<VirtuosoHandle>(null);

    // Use native find support when possible
    const setNativeFind = useStore((state) => state.appActions.setNativeFind);
    useEffect(() => {
      setNativeFind(!useVirtuoso);
    }, [setNativeFind, useVirtuoso]);

    useEffect(() => {
      const handleKeyDown = (event: KeyboardEvent) => {
        if (event.metaKey || event.ctrlKey) {
          if (event.key === "ArrowUp") {
            if (useVirtuoso) {
              listHandle.current?.scrollToIndex({ index: 0, align: "center" });
            } else {
              scrollRef?.current?.scrollTo({ top: 0, behavior: "instant" });
            }
            event.preventDefault();
          } else if (event.key === "ArrowDown") {
            if (useVirtuoso) {
              listHandle.current?.scrollToIndex({
                index: Math.max(messages.length - 5, 0),
                align: "center",
              });

              // This is needed to allow measurement to complete before finding
              // the last item to scroll to it properly. The timing isn't magical sadly
              // it is just a heuristic.
              setTimeout(() => {
                listHandle.current?.scrollToIndex({
                  index: messages.length - 1,
                  align: "end",
                });
              }, 250);
            } else {
              scrollRef?.current?.scrollTo({
                top: scrollRef.current.scrollHeight,
                behavior: "instant",
              });
            }
            event.preventDefault();
          }
        }
      };

      document.addEventListener("keydown", handleKeyDown);
      return () => {
        document.removeEventListener("keydown", handleKeyDown);
      };
    }, [scrollRef, messages, useVirtuoso]);

    if (!useVirtuoso) {
      return (
        <ChatView
          id={id}
          messages={messages}
          allowLinking={allowLinking}
          indented={indented}
          numbered={numbered}
          toolCallStyle={toolCallStyle}
          className={className}
        />
      );
    } else {
      return (
        <ChatViewVirtualListComponent
          id={id}
          listHandle={listHandle}
          className={className}
          scrollRef={scrollRef}
          messages={messages}
          initialMessageId={initialMessageId}
          topOffset={topOffset}
          toolCallStyle={toolCallStyle}
          indented={indented}
          numbered={numbered}
          running={running}
          allowLinking={allowLinking}
        />
      );
    }
  },
);

/**
 * Renders the ChatViewVirtualList component.
 */
export const ChatViewVirtualListComponent: FC<ChatViewVirtualListComponentProps> =
  memo(
    ({
      id,
      listHandle,
      messages,
      initialMessageId,
      topOffset,
      className,
      toolCallStyle,
      indented,
      numbered = true,
      scrollRef,
      running,
      allowLinking = true,
    }) => {
      const collapsedMessages = useMemo(() => {
        return resolveMessages(messages);
      }, [messages]);

      const initialMessageIndex = useMemo(() => {
        if (initialMessageId === null || initialMessageId === undefined) {
          return undefined;
        }

        const index = collapsedMessages.findIndex((message) => {
          const messageId = message.message.id === initialMessageId;
          if (messageId) {
            return true;
          }

          if (message.toolMessages.find((tm) => tm.id === initialMessageId)) {
            return true;
          }
        });
        return index !== -1 ? index : undefined;
      }, [initialMessageId, collapsedMessages]);

      const renderRow = useCallback(
        (index: number, item: ResolvedMessage): ReactNode => {
          const number =
            collapsedMessages.length > 1 && numbered ? index + 1 : undefined;
          const rowId = `${id}-msg-${index}`;
          return (
            <ChatMessageRow
              id={rowId}
              number={number}
              resolvedMessage={item}
              indented={indented}
              toolCallStyle={toolCallStyle}
              highlightUserMessage={true}
              allowLinking={allowLinking}
            />
          );
        },
        [
          collapsedMessages.length,
          numbered,
          id,
          indented,
          toolCallStyle,
          allowLinking,
        ],
      );

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
          listHandle={listHandle}
          className={className}
          scrollRef={scrollRef}
          data={collapsedMessages}
          renderRow={renderRow}
          initialTopMostItemIndex={initialMessageIndex}
          offsetTop={topOffset}
          live={running}
          showProgress={running}
          components={{ Item }}
          itemSearchText={messageSearchText}
        />
      );
    },
  );
