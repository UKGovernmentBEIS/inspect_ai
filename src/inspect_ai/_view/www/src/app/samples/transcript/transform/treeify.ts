import { Events } from "../../../../@types/log";
import { EventNode, EventType } from "../types";

/**
 * Gathers events into a hierarchy of EventNodes.
 */
export function treeifyEvents(events: Events, depth: number): EventNode[] {
  const rootNodes: EventNode[] = [];
  const stack: EventNode[] = [];

  const pushNode = (event: EventType): EventNode => {
    const node = new EventNode(event, stack.length + depth);
    if (stack.length > 0) {
      const parentNode = stack[stack.length - 1];
      parentNode.children.push(node);
    } else {
      rootNodes.push(node);
    }
    return node;
  };

  events.forEach((event) => {
    switch (event.event) {
      case "step":
        if (event.action === "begin") {
          // Starting a new step
          const node = pushNode(event);
          stack.push(node);
        } else {
          // An ending step
          if (stack.length > 0) {
            stack.pop();
          }
        }
        break;
      case "span_begin": {
        const node = pushNode(event);
        stack.push(node);
        break;
      }
      case "span_end": {
        if (stack.length > 0) {
          stack.pop();
        }
        break;
      }
      default:
        // An event
        pushNode(event);
        break;
    }
  });

  return rootNodes;
}
