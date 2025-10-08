import { Events, SpanBeginEvent, SpanEndEvent } from "../../../../@types/log";
import { EventNode, EventType } from "../types";
import { transformTree } from "./transform";
import {
  ACTION_BEGIN,
  SPAN_BEGIN,
  SPAN_END,
  STEP,
  TYPE_SCORER,
  TYPE_SCORERS,
  hasSpans,
} from "./utils";

export function treeifyEvents(events: Events, depth: number): EventNode[] {
  const useSpans = hasSpans(events);

  // First inject spans that may be needed
  events = injectScorersSpan(events);

  const nodes = useSpans
    ? treeifyWithSpans(events, depth)
    : treeifyWithSteps(events, depth);

  return useSpans ? transformTree(nodes) : nodes;
}

const treeifyWithSpans = (events: Events, depth: number): EventNode[] => {
  const { rootNodes, createNode } = createNodeFactory(depth);
  const spanNodes = new Map<string, EventNode>();

  const processEvent = (
    event: EventType,
    parentOverride?: EventNode | null,
  ) => {
    if (event.event === SPAN_END) {
      return;
    }

    if (event.event === STEP && event.action !== ACTION_BEGIN) {
      return;
    }

    const resolvedParent =
      parentOverride !== undefined
        ? parentOverride
        : resolveParentForEvent(event, spanNodes);
    const parentNode = resolvedParent ?? null;

    const node = createNode(event, parentNode);

    if (event.event === SPAN_BEGIN) {
      const spanId = getEventSpanId(event);
      if (spanId !== null) {
        spanNodes.set(spanId, node);
      }
    }
  };

  events.forEach((event) => processEvent(event));

  return rootNodes;
};

const treeifyWithSteps = (events: Events, depth: number): EventNode[] => {
  const { rootNodes, createNode } = createNodeFactory(depth);
  const stack: EventNode[] = [];

  const pushStack = (node: EventNode) => {
    stack.push(node);
  };

  const popStack = () => {
    if (stack.length > 0) {
      stack.pop();
    }
  };

  const processEvent = (event: EventType) => {
    const parent = stack.length > 0 ? stack[stack.length - 1] : null;

    switch (event.event) {
      case STEP:
        if (event.action === ACTION_BEGIN) {
          const node = createNode(event, parent);
          pushStack(node);
        } else {
          popStack();
        }
        break;
      case SPAN_BEGIN: {
        const node = createNode(event, parent);
        pushStack(node);
        break;
      }
      case SPAN_END:
        popStack();
        break;
      default:
        createNode(event, parent);
        break;
    }
  };

  events.forEach(processEvent);

  return rootNodes;
};

type NodeFactory = {
  rootNodes: EventNode[];
  createNode: (event: EventType, parent: EventNode | null) => EventNode;
};

const createNodeFactory = (depth: number): NodeFactory => {
  const rootNodes: EventNode[] = [];
  const childCounts = new Map<EventNode | null, number>();
  const pathByNode = new Map<EventNode, string>();

  const createNode = (
    event: EventType,
    parent: EventNode | null,
  ): EventNode => {
    const parentKey = parent ?? null;
    const nextIndex = childCounts.get(parentKey) ?? 0;
    childCounts.set(parentKey, nextIndex + 1);

    const parentPath = parent ? pathByNode.get(parent) : undefined;
    const path =
      parentPath !== undefined ? `${parentPath}.${nextIndex}` : `${nextIndex}`;

    const eventId = event.uuid || `event_node_${path}`;
    const nodeDepth = parent ? parent.depth + 1 : depth;

    const node = new EventNode(eventId, event, nodeDepth);
    pathByNode.set(node, path);

    if (parent) {
      parent.children.push(node);
    } else {
      rootNodes.push(node);
    }

    return node;
  };

  return { rootNodes, createNode };
};

const resolveParentForEvent = (
  event: EventType,
  spanNodes: Map<string, EventNode>,
): EventNode | null => {
  if (event.event === SPAN_BEGIN) {
    const parentId = event.parent_id;
    if (parentId) {
      return spanNodes.get(parentId) ?? null;
    }
    return null;
  }

  const spanId = getEventSpanId(event);
  if (spanId !== null) {
    return spanNodes.get(spanId) ?? null;
  }

  return null;
};

const getEventSpanId = (event: EventType): string | null => {
  const spanId = (event as { span_id?: string | null }).span_id;
  return spanId ?? null;
};

// This injects a scorer span around top level scorer events if one
// isn't already present
const kBeginScorerId = "E617087FA405";
const kEndScorerId = "C39922B09481";
const kScorersSpanId = "C5A831026F2C";
const injectScorersSpan = (events: Events): Events => {
  const results: Events = [];
  const collectedScorerEvents: Events = [];
  let hasCollectedScorers = false;
  let collecting: string | null = null;

  const flushCollected = (): Events => {
    if (collectedScorerEvents.length > 0) {
      const beginSpan: SpanBeginEvent = {
        name: "scorers",
        id: kBeginScorerId,
        span_id: kScorersSpanId,
        event: SPAN_BEGIN,
        type: TYPE_SCORERS,
        timestamp: collectedScorerEvents[0].timestamp,
        working_start: collectedScorerEvents[0].working_start,
        pending: false,
        parent_id: null,
        uuid: null,
        metadata: null,
      };

      const scoreEvents: Events = collectedScorerEvents.map((event) => {
        return {
          ...event,
          parent_id:
            event.event === "span_begin"
              ? event.parent_id || kScorersSpanId
              : null,
        };
      });

      const endSpan: SpanEndEvent = {
        id: kEndScorerId,
        span_id: kScorersSpanId,
        event: SPAN_END,
        pending: false,
        working_start:
          collectedScorerEvents[collectedScorerEvents.length - 1].working_start,
        timestamp:
          collectedScorerEvents[collectedScorerEvents.length - 1].timestamp,
        uuid: null,
        metadata: null,
      };

      collectedScorerEvents.length = 0;
      hasCollectedScorers = true;
      return [beginSpan, ...scoreEvents, endSpan];
    }
    return [];
  };

  for (const event of events) {
    // Return events immediately if the scorers span is present
    if (event.event === SPAN_BEGIN && event.type === TYPE_SCORERS) {
      return events;
    }

    if (
      event.event === SPAN_BEGIN &&
      event.type === TYPE_SCORER &&
      !hasCollectedScorers
    ) {
      collecting = event.span_id;
    }

    // Look for the first scorer event and then begin
    if (collecting) {
      if (event.event === SPAN_END && event.span_id === collecting) {
        collecting = null;
        results.push(...flushCollected());
        results.push(event);
      } else {
        collectedScorerEvents.push(event);
      }
    } else {
      results.push(event);
    }
  }

  return results;
};
