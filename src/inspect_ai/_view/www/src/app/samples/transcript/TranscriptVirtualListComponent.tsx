import clsx from "clsx";
import {
  CSSProperties,
  FC,
  RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
} from "react";
import {
  ContentAudio,
  ContentImage,
  ContentText,
  ContentVideo,
  ToolEvent,
} from "../../../@types/log";
import { EventNodeContext, RenderedEventNode } from "./TranscriptVirtualList";
import { EventNode } from "./types";
import {
  BROWSER_TOOL_FUNCTIONS,
  buildSelfAnnotation,
  isBrowserScreenshot,
  isVisualBrowserAction,
} from "../chat/tools/browserActionUtils";

import { VirtuosoHandle } from "react-virtuoso";
import { LiveVirtualList } from "../../../components/LiveVirtualList";
import { useStore } from "../../../state/store";
import styles from "./TranscriptVirtualListComponent.module.css";
import { eventSearchText } from "./eventSearchText";

interface TranscriptVirtualListComponentProps {
  id: string;
  listHandle: RefObject<VirtuosoHandle | null>;
  eventNodes: EventNode[];
  initialEventId?: string | null;
  offsetTop?: number;
  scrollRef?: RefObject<HTMLDivElement | null>;
  running?: boolean;
  className?: string | string[];
  turnMap?: Map<string, { turnNumber: number; totalTurns: number }>;
}

/**
 * Renders the Transcript component.
 */
export const TranscriptVirtualListComponent: FC<
  TranscriptVirtualListComponentProps
> = ({
  id,
  listHandle,
  eventNodes,
  scrollRef,
  running,
  initialEventId,
  offsetTop,
  className,
  turnMap,
}) => {
  const useVirtualization = running || eventNodes.length > 100;
  const setNativeFind = useStore((state) => state.appActions.setNativeFind);
  useEffect(() => {
    setNativeFind(!useVirtualization);
  }, [setNativeFind, useVirtualization]);

  const initialEventIndex = useMemo(() => {
    if (initialEventId === null || initialEventId === undefined) {
      return undefined;
    }
    const result = eventNodes.findIndex((event) => {
      return event.id === initialEventId;
    });
    return result === -1 ? undefined : result;
  }, [initialEventId, eventNodes]);

  const hasToolEventsAtCurrentDepth = useCallback(
    (startIndex: number) => {
      // Walk backwards from this index to see if we see any tool events
      // at this depth, prior to this event
      for (let i = startIndex; i >= 0; i--) {
        const node = eventNodes[i];
        if (node.event.event === "tool") {
          return true;
        }
        if (node.depth < eventNodes[startIndex].depth) {
          return false;
        }
      }
      return false;
    },
    [eventNodes],
  );

  const nonVirtualGridRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!useVirtualization && initialEventId) {
      const row = nonVirtualGridRef.current?.querySelector(
        `[id="${initialEventId}"]`,
      );
      row?.scrollIntoView({ block: "start" });
    }
  }, [initialEventId, useVirtualization]);

  // Pre-compute context objects for all event nodes to maintain stable references
  const contextMap = useMemo(() => {
    const map = new Map<string, EventNodeContext>();
    for (let i = 0; i < eventNodes.length; i++) {
      const node = eventNodes[i];
      const hasToolEvents = hasToolEventsAtCurrentDepth(i);
      const turnInfo = turnMap?.get(node.id);
      const { inputScreenshot, selfAnnotation } = computeVisualActionContext(
        eventNodes,
        i,
      );
      const nextEvent = eventNodes[i + 1];
      const showToolCalls = nextEvent ? nextEvent.event.event !== "tool" : true;
      map.set(node.id, {
        hasToolEvents,
        turnInfo,
        inputScreenshot,
        selfAnnotation,
        showToolCalls,
      });
    }
    return map;
  }, [eventNodes, hasToolEventsAtCurrentDepth, turnMap]);

  const renderRow = useCallback(
    (index: number, item: EventNode, style?: CSSProperties) => {
      const paddingClass = index === 0 ? styles.first : undefined;
      const { attachedClass, attachedChildClass, attachedParentClass } =
        computeAttachedClasses(eventNodes, index);

      const context = contextMap.get(item.id);

      return (
        <div
          id={item.id}
          key={item.id}
          className={clsx(styles.node, paddingClass, attachedClass)}
          style={{
            ...style,
            paddingLeft: `${item.depth <= 1 ? item.depth * 0.7 : (0.7 + item.depth - 1) * 1}em`,
            paddingRight: `${item.depth === 0 ? undefined : ".7em"} `,
          }}
        >
          <RenderedEventNode
            node={item}
            className={clsx(attachedParentClass, attachedChildClass)}
            context={context}
          />
        </div>
      );
    },
    [eventNodes, contextMap],
  );

  if (useVirtualization) {
    return (
      <LiveVirtualList<EventNode>
        listHandle={listHandle}
        className={className}
        id={id}
        scrollRef={scrollRef}
        data={eventNodes}
        initialTopMostItemIndex={initialEventIndex}
        offsetTop={offsetTop}
        renderRow={renderRow}
        live={running}
        itemSearchText={eventSearchText}
      />
    );
  } else {
    return (
      <div ref={nonVirtualGridRef}>
        {eventNodes.map((node, index) => {
          const row = renderRow(index, node, {
            scrollMarginTop: offsetTop,
          });
          return row;
        })}
      </div>
    );
  }
};

/**
 * For a visual browser action tool event (click/scroll/type) at the given
 * index, walk backward through the flat event list to find the preceding
 * screenshot and return its result as normalized content.  Also build the
 * self-annotation from the action's own arguments.
 *
 * Returns { inputScreenshot, selfAnnotation } — both undefined if the event
 * is not a visual browser action or no preceding screenshot is found.
 */
function computeVisualActionContext(
  eventNodes: EventNode[],
  index: number,
): {
  inputScreenshot?: (
    | ContentText
    | ContentImage
    | ContentAudio
    | ContentVideo
  )[];
  selfAnnotation?: import("../chat/tools/AnnotatedToolOutput").ToolAnnotation;
} {
  const node = eventNodes[index];
  if (node.event.event !== "tool") return {};

  const toolEvent = node.event as ToolEvent;
  const args = toolEvent.arguments as Record<string, unknown>;
  if (!isVisualBrowserAction(toolEvent.function, args)) return {};

  const selfAnnotation = buildSelfAnnotation(toolEvent.function, args);

  // Walk backward to find the preceding screenshot.
  // The list interleaves model, span_begin, sandbox events between tools.
  for (let i = index - 1; i >= 0 && i >= index - 30; i--) {
    const candidate = eventNodes[i];
    if (candidate.event.event !== "tool") continue;
    const candEvent = candidate.event as ToolEvent;
    if (!BROWSER_TOOL_FUNCTIONS.has(candEvent.function)) break;
    const candArgs = candEvent.arguments as Record<string, unknown>;
    if (isBrowserScreenshot(candEvent.function, candArgs)) {
      const result = candEvent.result;
      const inputScreenshot = normalizeScreenshotResult(result);
      return { inputScreenshot, selfAnnotation };
    }
  }

  // No preceding screenshot found — still return the annotation so the
  // tool call renders normally (just without the Input tab).
  return { selfAnnotation: undefined };
}

/**
 * Normalize a ToolEvent.result into a flat content array suitable for
 * MessageContent rendering.
 */
function normalizeScreenshotResult(
  result:
    | string
    | number
    | boolean
    | ContentText
    | ContentImage
    | ContentAudio
    | ContentVideo
    | (ContentText | ContentImage | ContentAudio | ContentVideo)[],
): (ContentText | ContentImage | ContentAudio | ContentVideo)[] | undefined {
  if (Array.isArray(result)) return result;
  if (result && typeof result === "object" && "type" in result) {
    return [result as ContentText | ContentImage | ContentAudio | ContentVideo];
  }
  // String/number/boolean results don't contain images — skip.
  return undefined;
}

/**
 * Determine attached/parent CSS classes for a row based on its neighbours.
 * Tool events following a model or another tool are "attached" (visually
 * grouped); model events preceding a tool are "attached parents".
 */
function computeAttachedClasses(eventNodes: EventNode[], index: number) {
  const item = eventNodes[index];
  const previous = index > 0 ? eventNodes[index - 1] : undefined;
  const next =
    index + 1 < eventNodes.length ? eventNodes[index + 1] : undefined;

  const attached =
    item.event.event === "tool" &&
    (previous?.event.event === "tool" || previous?.event.event === "model");
  const attachedParent =
    item.event.event === "model" && next?.event.event === "tool";

  return {
    attachedClass: attached ? styles.attached : undefined,
    attachedChildClass: attached ? styles.attachedChild : undefined,
    attachedParentClass: attachedParent ? styles.attachedParent : undefined,
  };
}
