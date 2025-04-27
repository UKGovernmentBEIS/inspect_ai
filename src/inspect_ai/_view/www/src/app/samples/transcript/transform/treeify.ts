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
 * Process a span node by elevating a specific child node type and moving its siblings as children
 * @template T - Type of the event (either ToolEvent or SubtaskEvent)
 */
const processSpanNode = <T extends ToolEvent | SubtaskEvent>(
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

const fixupTree = (roots: EventNode[]): EventNode[] => {
  const results: EventNode[] = [];

  for (const node of roots) {
    if (node.event.event === "span_begin" && node.event["type"] === "subtask") {
      const processedNode = processSpanNode<SubtaskEvent>(node, "subtask");
      if (processedNode) {
        results.push(processedNode);
      } else {
        // If processing failed, still process children recursively
        node.children = fixupTree(node.children);
        results.push(node);
      }
    } else if (
      node.event.event === "span_begin" &&
      node.event["type"] === "tool"
    ) {
      const processedNode = processSpanNode<ToolEvent>(node, "tool");
      if (processedNode) {
        results.push(processedNode);
      } else {
        // If processing failed, still process children recursively
        node.children = fixupTree(node.children);
        results.push(node);
      }
    } else if (node.event.event === "span_begin") {
      // Process children recursively for non-tool, non-subtask spans
      node.children = fixupTree(node.children);
      results.push(node);
    } else {
      results.push(node);
    }
  }

  return results;
};
