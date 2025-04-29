import { Events, SubtaskEvent, ToolEvent } from "../../../../@types/log";
import { EventNode, EventType } from "../types";

const ET_STEP = "step";
const ACTION_BEGIN = "begin";

const ET_SPAN_BEGIN = "span_begin";
const ET_SPAN_END = "span_end";

type TreeifyFunction = (
  event: EventType,
  addNode: (event: EventType) => EventNode,
  pushStack: (node: EventNode) => void,
  popStack: () => void,
) => void;

export function treeifyEvents(events: Events, depth: number): EventNode[] {
  const hasSpans = events.some((event) => event.event === ET_SPAN_BEGIN);
  const treeFn = hasSpans ? treeifyFnSpan : treeifyFnStep;

  const rootNodes: EventNode[] = [];
  const stack: EventNode[] = [];

  const addNode = (event: EventType): EventNode => {
    const node = new EventNode(event, stack.length + depth);
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
    if (stack.length > 0) {
      stack.pop();
    }
  };

  events.forEach((event) => {
    treeFn(event, addNode, pushStack, popStack);
  });

  if (hasSpans) {
    return fixupTree(rootNodes);
  } else {
    return rootNodes;
  }
}

const treeifyFnStep: TreeifyFunction = (
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
      // These shoudn't be here, but throw away
      break;
    }
    case ET_SPAN_END: {
      // These shoudn't be here, but throw away
      break;
    }
    default:
      // An event
      addNode(event);
      break;
  }
};

const treeifyFnSpan: TreeifyFunction = (
  event: EventType,
  addNode: (event: EventType) => EventNode,
  pushStack: (node: EventNode) => void,
  popStack: () => void,
): void => {
  switch (event.event) {
    case ET_STEP:
      // strip steps
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

/**
 * Fixup the tree by processing spans and moving their children
 * @param roots - The root nodes of the event tree
 * @returns The fixed-up event tree
 */
const fixupTree = (roots: EventNode[]): EventNode[] => {
  const results: EventNode[] = [];

  for (const node of roots) {
    let processed = false;
    for (const processor of spanProcessors) {
      if (processor.shouldProcess(node)) {
        const processedNode = processor.process(node);
        results.push(processedNode);
        break;
      }
    }
    if (!processed) {
      results.push(node);
    }
  }

  return results;
};

/**
 * Process a span node by elevating a specific child node type and moving its siblings as children
 * @template T - Type of the event (either ToolEvent or SubtaskEvent)
 */
const elevateChildNode = <T extends ToolEvent | SubtaskEvent>(
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
  const targetNode = node.children[targetIndex];
  targetNode.depth = node.depth;

  // Process the remaining children
  const remainingChildren = node.children.filter((_, i) => i !== targetIndex);
  targetNode.children = remainingChildren.map((child) => {
    child.depth = child.depth - 1;
    return child;
  });

  // Process children recursively
  // We need to process children here because they might contain nested tool/subtask spans
  targetNode.children = fixupTree(targetNode.children);

  // Move the children events to the target event
  const targetEvent = targetNode.event as T;
  const newEvent: T = {
    ...targetEvent,
    events: targetNode.children.map((child) => child.event),
  };
  targetNode.event = newEvent as EventType;

  return targetNode;
};

// Reduce the depth of the children by 1
// This is used when we hoist a child node to the parent
const reduceDepth = (nodes: EventNode[]): EventNode[] => {
  return nodes.map((node) => {
    const newNode = { ...node, depth: node.depth - 1 };
    if (node.children.length > 0) {
      newNode.children = reduceDepth(node.children);
    }
    return newNode;
  });
};

interface SpanProcessor {
  shouldProcess: (node: EventNode) => boolean;
  process: (node: EventNode) => EventNode;
}

const defaultSpanProcessor: SpanProcessor = {
  shouldProcess: (node: EventNode): boolean => {
    return node.event.event === "span_begin";
  },
  process: (node: EventNode): EventNode => {
    // Process children recursively for non-tool, non-subtask spans
    node.children = fixupTree(node.children);
    return node;
  },
};

const toolSpanProcessor: SpanProcessor = {
  shouldProcess: (node: EventNode): boolean => {
    return node.event.event === "span_begin" && node.event["type"] === "tool";
  },
  process: (node: EventNode): EventNode => {
    const processedNode = elevateChildNode<ToolEvent>(node, "tool");
    if (processedNode) {
      return processedNode;
    } else {
      // If processing failed, still process children recursively
      node.children = fixupTree(node.children);
      return node;
    }
  },
};

const subtaskSpanProcessor: SpanProcessor = {
  shouldProcess: (node: EventNode): boolean => {
    return (
      node.event.event === "span_begin" && node.event["type"] === "subtask"
    );
  },
  process: (node: EventNode): EventNode => {
    const processedNode = elevateChildNode<SubtaskEvent>(node, "subtask");
    if (processedNode) {
      return processedNode;
    } else {
      // If processing failed, still process children recursively
      node.children = fixupTree(node.children);
      return node;
    }
  },
};

const solverAgentSpanProcessor: SpanProcessor = {
  shouldProcess: (node: EventNode): boolean => {
    return (
      node.event.event === "span_begin" &&
      node.event["type"] === "solver" &&
      node.children.length === 2 &&
      node.children[0].event.event === "span_begin" &&
      node.children[0].event.type === "agent" &&
      node.children[1].event.event === "state"
    );
  },
  process: (node: EventNode): EventNode => {
    // If the solver only contains a single agent span and a state, we can
    // hoist the agent span and ignore the solver

    // Discard the agent span
    const agentSpan = node.children.splice(0, 1)[0];
    node.children.unshift(...reduceDepth(agentSpan.children));
    node.children = fixupTree(node.children);

    return node;
  },
};

const spanProcessors: SpanProcessor[] = [
  subtaskSpanProcessor,
  toolSpanProcessor,
  solverAgentSpanProcessor,
  defaultSpanProcessor,
];
