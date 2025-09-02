import {
  FC,
  memo,
  ReactNode,
  RefObject,
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

import {
  ContextProp,
  ItemProps,
  ListRange,
  VirtuosoHandle,
} from "react-virtuoso";
import { useStore } from "../../../state/store";
import { findMessageIndexes } from "../../find/message";
import { highlightNthOccurrence } from "../../find/util";
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

    // The list handle
    const listHandle = useRef<VirtuosoHandle>(null);

    // Find state
    const searching = useStore((state) => state.app.find.searching);
    const findIndex = useStore((state) => state.app.find.index);
    const findResults = useStore((state) => state.app.find.results);
    const setFindIndex = useStore((state) => state.appActions.setFindIndex);
    const setFindResults = useStore((state) => state.appActions.setFindResults);
    const term = useStore((state) => state.app.find.term);

    useEffect(() => {
      if (term && searching) {
        const result = findMessageIndexes(
          term,
          collapsedMessages.map((m) => m.message),
        );
        setFindIndex(0);
        setFindResults(result);
      }
    }, [collapsedMessages, searching, term]);

    useEffect(() => {
      // Turn the dictionary into an array of message indexes
      const arr: number[] = [];

      if (findResults) {
        for (const [key, count] of Object.entries(findResults)) {
          arr.push(...Array(count).fill(parseInt(key)));
        }
      }

      if (findIndex !== undefined && findIndex > -1 && findIndex < arr.length) {
        // Scroll to the message with the findIndex
        listHandle.current?.scrollToIndex({
          index: arr[findIndex],
          align: "center",
        });
        setTimeout(() => {
          const el = rowRefs.current[arr[findIndex]];
          if (term && el && el.parentElement) {
            highlightNthOccurrence(el.parentElement, term, 1);
          }
        }, 100);
      }
    }, [findResults, findIndex, term]);

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

    const rowRefs = useRef<Record<number, HTMLDivElement | null>>({});

    const renderRow = (index: number, item: ResolvedMessage): ReactNode => {
      const number =
        collapsedMessages.length > 1 && numbered ? index + 1 : undefined;

      return (
        <ChatMessageRow
          ref={(el: HTMLDivElement | null) => {
            rowRefs.current[index] = el;
          }}
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
        listHandle={listHandle}
        rangeChanged={(range: ListRange) => {
          // Clean up refs outside the current range
          Object.keys(rowRefs.current).forEach((indexStr) => {
            const index = parseInt(indexStr, 10);
            if (index < range.startIndex || index > range.endIndex) {
              delete rowRefs.current[index];
            }
          });
        }}
      />
    );
  },
);
