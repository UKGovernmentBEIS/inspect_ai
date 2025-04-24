import { Events } from "../../../../@types/log";
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
  return rootNodes;
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
