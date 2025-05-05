import { Events } from "../../../../@types/log";
import { EventNode, EventType } from "../types";
import {
  ACTION_BEGIN,
  ET_SPAN_BEGIN,
  ET_SPAN_END,
  ET_STEP,
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
    const node = new EventNode(idPath, event, currentDepth + depth);
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

  events.forEach((event) => {
    treeifyFn(event, addNode, pushStack, popStack);
  });

  if (useSpans) {
    return transformTree(rootNodes);
  } else {
    return rootNodes;
  }
}

const treeifyFn: TreeifyFunction = (
  event: EventType,
  addNode: (event: EventType) => EventNode,
  pushStack: (node: EventNode) => void,
  popStack: () => void,
): void => {
  switch (event.event) {
    case ET_STEP:
      if (event.action === ACTION_BEGIN) {
        // Starting a new step
        const node = addNode(event);
        pushStack(node);
      } else {
        // An ending step
        popStack();
      }
      break;
    case ET_SPAN_BEGIN: {
      const node = addNode(event);
      pushStack(node);
      break;
    }
    case ET_SPAN_END: {
      popStack();
      break;
    }
    default:
      // An event
      addNode(event);
      break;
  }
};

type TreeNodeTransformer = {
  name: string;
  matches: (node: EventNode) => boolean;
  process: (node: EventNode) => EventNode;
};

const treeNodeTransformers: TreeNodeTransformer[] = [
  {
    name: "unwrap_tools",
    matches: (node) =>
      node.event.event === "span_begin" && node.event.type === "tool",
    process: (node) => elevateChildNode(node, "tool") || node,
  },
  {
    name: "unwrap_subtasks",
    matches: (node) =>
      node.event.event === "span_begin" && node.event.type === "subtask",
    process: (node) => elevateChildNode(node, "subtask") || node,
  },
  {
    name: "unwrap_agent_solver",
    matches: (node) =>
      node.event.event === "span_begin" &&
      node.event["type"] === "solver" &&
      node.children.length === 2 &&
      node.children[0].event.event === "span_begin" &&
      node.children[0].event.type === "agent" &&
      node.children[1].event.event === "state",

    process: (node) => skipFirstChildNode(node),
  },
  {
    name: "unwrap_agent_solver w/store",
    matches: (node) =>
      node.event.event === "span_begin" &&
      node.event["type"] === "solver" &&
      node.children.length === 3 &&
      node.children[0].event.event === "span_begin" &&
      node.children[0].event.type === "agent" &&
      node.children[1].event.event === "state" &&
      node.children[2].event.event === "store",
    process: (node) => skipFirstChildNode(node),
  },
  {
    name: "unwrap_handoff",
    matches: (node) =>
      node.event.event === "span_begin" &&
      node.event["type"] === "handoff" &&
      node.children.length === 2 &&
      node.children[0].event.event === "tool" &&
      node.children[1].event.event === "store" &&
      node.children[0].children.length === 2 &&
      node.children[0].children[0].event.event === "span_begin" &&
      node.children[0].children[0].event.type === "agent",
    process: (node) => skipThisNode(node),
  },
];

const transformTree = (roots: EventNode[]): EventNode[] => {
  const visitNode = (node: EventNode): EventNode => {
    let processedNode = node;

    // Visit children (depth first)
    processedNode.children = processedNode.children.map(visitNode);

    // Apply any visitors to this node
    for (const transformer of treeNodeTransformers) {
      if (transformer.matches(processedNode)) {
        processedNode = transformer.process(processedNode);
        // Only apply the first matching transformer
        break;
      }
    }
    return processedNode;
  };

  return roots.map(visitNode);
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
  targetNode.children = reduceDepth(remainingChildren);

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

/**
 * Flatten the tree structure into a flat array of EventNode objects
 * Each node in the result will have its children set properly
 * @param events - The events to flatten
 * @param depth - The current depth in the tree
 * @returns An array of EventNode objects
 */
export const flatTree = (
  eventNodes: EventNode[],
  collapsed: Set<string>,
): EventNode[] => {
  const result: EventNode[] = [];
  for (const node of eventNodes) {
    result.push(node);
    if (!collapsed.has(node.id)) {
      result.push(...flatTree(node.children, collapsed));
    }
  }
  return result;
};
