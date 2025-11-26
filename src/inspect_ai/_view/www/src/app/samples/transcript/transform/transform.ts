import { EventNode } from "../types";
import {
  SPAN_BEGIN,
  STATE,
  STORE,
  TOOL,
  TYPE_AGENT,
  TYPE_HANDOFF,
  TYPE_SOLVER,
  TYPE_SOLVERS,
  TYPE_SUBTASK,
  TYPE_TOOL,
} from "./utils";

export const transformTree = (roots: EventNode[]): EventNode[] => {
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
      matches: (node) => {
        const isHandoffNode =
          node.event.event === SPAN_BEGIN &&
          node.event["type"] === TYPE_HANDOFF;

        if (!isHandoffNode) {
          return false;
        }

        if (node.children.length === 1) {
          return (
            node.children[0].event.event === TOOL &&
            !!node.children[0].event.agent
          );
        } else {
          return (
            node.children.length === 2 &&
            node.children[0].event.event === TOOL &&
            node.children[1].event.event === STORE &&
            node.children[0].children.length === 2 &&
            node.children[0].children[0].event.event === SPAN_BEGIN &&
            node.children[0].children[0].event.type === TYPE_AGENT
          );
        }
      },
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
  newNode.children = reduceDepth(newNode.children, 2);
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
