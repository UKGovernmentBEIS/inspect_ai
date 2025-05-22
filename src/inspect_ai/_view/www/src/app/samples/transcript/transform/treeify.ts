import { Events, SpanBeginEvent, SpanEndEvent } from "../../../../@types/log";
import { EventNode, EventType } from "../types";
import {
  ACTION_BEGIN,
  SPAN_BEGIN,
  SPAN_END,
  STATE,
  STEP,
  STORE,
  SUBTASK,
  TOOL,
  TYPE_AGENT,
  TYPE_HANDOFF,
  TYPE_SCORER,
  TYPE_SCORERS,
  TYPE_SOLVER,
  TYPE_SOLVERS,
  TYPE_SUBTASK,
  TYPE_TOOL,
  hasSpans,
} from "./utils";

type TreeifyFunction = (
  event: EventType,
  addNode: (event: EventType) => EventNode,
  pushStack: (node: EventNode) => void,
  popStack: () => void,
) => void;

export function treeifyEvents(events: Events, depth: number): EventNode[] {
  const useSpans = hasSpans(events);
  const pathIndices: number[] = [];

  const rootNodes: EventNode[] = [];
  const stack: EventNode[] = [];

  // The function used to build the tree
  const treeifyFn = getTreeifyFunction();

  const addNode = (event: EventType): EventNode => {
    const currentDepth = stack.length;

    // Track sibling count for the parent node
    if (pathIndices.length <= currentDepth) {
      pathIndices.push(0);
    } else {
      pathIndices[currentDepth]++;
      // Reset deeper levels if coming back up the stack
      pathIndices.length = currentDepth + 1;
    }

    // Create a new node
    const idPath = pathIndices.slice(0, currentDepth + 1).join(".");
    const node = new EventNode(
      `event_node_${idPath}`,
      event,
      currentDepth + depth,
    );
    if (stack.length > 0) {
      const parentNode = stack[stack.length - 1];
      parentNode.children.push(node);
    } else {
      rootNodes.push(node);
    }

    return node;
  };

  const pushStack = (node: EventNode): void => {
    stack.push(node);
  };

  const popStack = (): void => {
    stack.pop();
    pathIndices.pop();
  };

  // First inject spans that may be needed
  events = injectScorersSpan(events);

  // Now treeify the list
  events.forEach((event) => {
    treeifyFn(event, addNode, pushStack, popStack);
  });

  if (useSpans) {
    return transformTree(rootNodes);
  } else {
    return rootNodes;
  }
}

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

const getTreeifyFunction = () => {
  const treeifyFn: TreeifyFunction = (
    event: EventType,
    addNode: (event: EventType) => EventNode,
    pushStack: (node: EventNode) => void,
    popStack: () => void,
  ): void => {
    switch (event.event) {
      case STEP:
        if (event.action === ACTION_BEGIN) {
          // Starting a new step
          const node = addNode(event);
          pushStack(node);
        } else {
          // An ending step
          popStack();
        }
        break;
      case SPAN_BEGIN: {
        const node = addNode(event);
        pushStack(node);
        break;
      }
      case SPAN_END: {
        popStack();
        break;
      }
      case TOOL:
        {
          const node = addNode(event);

          // In the span world, the first child will be a span of type tool
          if (
            event.events.length > 0 &&
            (event.events[0].event !== SPAN_BEGIN ||
              event.events[0].type !== TYPE_TOOL)
          ) {
            // Expand the children
            pushStack(node);
            for (const child of event.events) {
              treeifyFn(child, addNode, pushStack, popStack);
            }
            popStack();
          }
        }

        break;
      case SUBTASK:
        {
          const node = addNode(event);

          // In the span world, the first child will be a span of type tool
          if (
            event.events.length > 0 &&
            (event.events[0].event !== SPAN_BEGIN ||
              event.events[0].type !== TYPE_SUBTASK)
          ) {
            // Expand the children
            pushStack(node);
            for (const child of event.events) {
              treeifyFn(child, addNode, pushStack, popStack);
            }
            popStack();
          }
        }

        break;

      default:
        // An event
        addNode(event);
        break;
    }
  };
  return treeifyFn;
};

const transformTree = (roots: EventNode[]): EventNode[] => {
  // Gather the transformers that we'll use
  const treeNodeTransformers: TreeNodeTransformer[] = transformers();

  const visitNode = (node: EventNode): EventNode | EventNode[] => {
    // Start with the original node
    let currentNodes: EventNode[] = [node];

    // Process children of all nodes first (depth-first)
    currentNodes = currentNodes.map((n) => {
      n.children = n.children.flatMap(visitNode);
      return n;
    });

    // Apply each transformer to all nodes that match
    for (const transformer of treeNodeTransformers) {
      const nextNodes: EventNode[] = [];

      // Process each current node with this transformer
      for (const currentNode of currentNodes) {
        if (transformer.matches(currentNode)) {
          const result = transformer.process(currentNode);
          if (Array.isArray(result)) {
            nextNodes.push(...result);
          } else {
            nextNodes.push(result);
          }
        } else {
          // Node doesn't match this transformer, keep it unchanged
          nextNodes.push(currentNode);
        }
      }

      // Update current nodes for next transformer
      currentNodes = nextNodes;
    }

    // Return all processed nodes
    return currentNodes.length === 1 ? currentNodes[0] : currentNodes;
  };

  // Process all nodes first
  const processedRoots = roots.flatMap(visitNode);

  // Call flush on any transformers that have it
  const flushedNodes: EventNode[] = [];
  for (const transformer of treeNodeTransformers) {
    if (transformer.flush) {
      const flushResults = transformer.flush();
      if (flushResults && flushResults.length > 0) {
        flushedNodes.push(...flushResults);
      }
    }
  }

  return [...processedRoots, ...flushedNodes];
};

const transformers = () => {
  const treeNodeTransformers: TreeNodeTransformer[] = [
    {
      name: "unwrap_tools",
      matches: (node) =>
        node.event.event === SPAN_BEGIN && node.event.type === TYPE_TOOL,
      process: (node) => elevateChildNode(node, TYPE_TOOL) || node,
    },
    {
      name: "unwrap_subtasks",
      matches: (node) =>
        node.event.event === SPAN_BEGIN && node.event.type === TYPE_SUBTASK,
      process: (node) => elevateChildNode(node, TYPE_SUBTASK) || node,
    },
    {
      name: "unwrap_agent_solver",
      matches: (node) =>
        node.event.event === SPAN_BEGIN &&
        node.event["type"] === TYPE_SOLVER &&
        node.children.length === 2 &&
        node.children[0].event.event === SPAN_BEGIN &&
        node.children[0].event.type === TYPE_AGENT &&
        node.children[1].event.event === STATE,

      process: (node) => skipFirstChildNode(node),
    },
    {
      name: "unwrap_agent_solver w/store",
      matches: (node) =>
        node.event.event === SPAN_BEGIN &&
        node.event["type"] === TYPE_SOLVER &&
        node.children.length === 3 &&
        node.children[0].event.event === SPAN_BEGIN &&
        node.children[0].event.type === TYPE_AGENT &&
        node.children[1].event.event === STATE &&
        node.children[2].event.event === STORE,
      process: (node) => skipFirstChildNode(node),
    },
    {
      name: "unwrap_handoff",
      matches: (node) =>
        node.event.event === SPAN_BEGIN &&
        node.event["type"] === TYPE_HANDOFF &&
        node.children.length === 2 &&
        node.children[0].event.event === TOOL &&
        node.children[1].event.event === STORE &&
        node.children[0].children.length === 2 &&
        node.children[0].children[0].event.event === SPAN_BEGIN &&
        node.children[0].children[0].event.type === TYPE_AGENT,
      process: (node) => skipThisNode(node),
    },
    {
      name: "discard_solvers_span",
      matches: (Node) =>
        Node.event.event === SPAN_BEGIN && Node.event.type === TYPE_SOLVERS,
      process: (node) => {
        const nodes = discardNode(node);
        return nodes;
      },
    },
  ];
  return treeNodeTransformers;
};

type TreeNodeTransformer = {
  name: string;
  matches: (node: EventNode) => boolean;
  process: (node: EventNode) => EventNode | EventNode[];
  flush?: () => EventNode[];
};

/**
 * Process a span node by elevating a specific child node type and moving its siblings as children
 * @template T - Type of the event (either ToolEvent or SubtaskEvent)
 */
const elevateChildNode = (
  node: EventNode,
  childEventType: "tool" | "subtask",
): EventNode | null => {
  // Find the specific event child
  const targetIndex = node.children.findIndex(
    (child) => child.event.event === childEventType,
  );

  if (targetIndex === -1) {
    console.log(
      `No ${childEventType} event found in a span, this is very unexpected.`,
    );
    return null;
  }

  // Get the target node and set its depth
  const targetNode = { ...node.children[targetIndex] };
  const remainingChildren = node.children.filter((_, i) => i !== targetIndex);

  // Process the remaining children
  targetNode.depth = node.depth;
  targetNode.children = setDepth(remainingChildren, node.depth + 1);

  // No need to update the event itself (events have been deprecated
  // and more importantly we drive children / transcripts using the tree structure itself
  // and notes rather than the event.events itself)
  return targetNode;
};

const skipFirstChildNode = (node: EventNode): EventNode => {
  const agentSpan = node.children.splice(0, 1)[0];
  node.children.unshift(...reduceDepth(agentSpan.children));
  return node;
};

const skipThisNode = (node: EventNode): EventNode => {
  const newNode = { ...node.children[0] };
  newNode.depth = node.depth;
  newNode.children = reduceDepth(newNode.children[0].children, 2);
  return newNode;
};

const discardNode = (node: EventNode): EventNode[] => {
  const nodes = reduceDepth(node.children, 1);
  return nodes;
};

// Reduce the depth of the children by 1
// This is used when we hoist a child node to the parent
const reduceDepth = (nodes: EventNode[], depth: number = 1): EventNode[] => {
  return nodes.map((node) => {
    if (node.children.length > 0) {
      node.children = reduceDepth(node.children, 1);
    }
    node.depth = node.depth - depth;
    return node;
  });
};

const setDepth = (nodes: EventNode[], depth: number): EventNode[] => {
  return nodes.map((node) => {
    if (node.children.length > 0) {
      node.children = setDepth(node.children, depth + 1);
    }
    node.depth = depth;
    return node;
  });
};

export interface TreeNodeVisitor {
  visit: (node: EventNode, parent?: EventNode) => EventNode[];
  flush?: () => EventNode[];
}

/**
 * Flatten the tree structure into a flat array of EventNode objects
 * Each node in the result will have its children set properly
 * @param eventNodes - The event nodes to flatten
 * @param collapsed - Record indicating which nodes are collapsed
 * @param visitors - Array of visitors to apply to each node
 * @param parentNode - The parent node of the current nodes being processed
 * @returns An array of EventNode objects
 */
export const flatTree = (
  eventNodes: EventNode[],
  collapsed: Record<string, boolean> | null,
  visitors?: TreeNodeVisitor[],
  parentNode?: EventNode,
): EventNode[] => {
  const result: EventNode[] = [];
  for (const node of eventNodes) {
    if (visitors && visitors.length > 0) {
      let pendingNodes: EventNode[] = [{ ...node }];

      for (const visitor of visitors) {
        const allResults: EventNode[] = [];
        for (const pendingNode of pendingNodes) {
          const visitorResult = visitor.visit(pendingNode);
          if (parentNode) {
            parentNode.children = visitorResult;
          }
          allResults.push(...visitorResult);
        }
        pendingNodes = allResults;
      }

      for (const pendingNode of pendingNodes) {
        const children = flatTree(
          pendingNode.children,
          collapsed,
          visitors,
          pendingNode,
        );
        pendingNode.children = children;
        result.push(pendingNode);
        if (collapsed === null || collapsed[pendingNode.id] !== true) {
          result.push(...children);
        }
      }

      for (const visitor of visitors) {
        if (visitor.flush) {
          const finalNodes = visitor.flush();
          result.push(...finalNodes);
        }
      }
    } else {
      result.push(node);
      const children = flatTree(node.children, collapsed, visitors, node);
      if (collapsed === null || collapsed[node.id] !== true) {
        result.push(...children);
      }
    }
  }

  return result;
};
